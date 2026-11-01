"""Business rules shared by web routes and Excel imports.

Each state change reads and writes under one database write transaction. Do not
call these services from a transaction opened by the controller.
"""
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from models.repository import get_db, record_audit, record_inventory_movement, using_turso

EPSILON = 0.0000001


def now():
    return datetime.now().isoformat(timespec='seconds')


def quantity(value, integer=False):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0 or number > 1_000_000_000:
            raise ValueError
        if integer and number != number.to_integral_value():
            raise ValueError
        if number != number.quantize(Decimal('0.000001')):
            raise ValueError
        return int(number) if integer else float(number)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Số lượng phải lớn hơn 0, tối đa 1 tỷ và có tối đa 6 chữ số thập phân.')


def insert_rows(db, prefix, rows, suffix=''):
    """Insert parameterized chunks; the HTTP driver executes executemany per row."""
    rows=list(rows)
    if not rows:
        return
    width=len(rows[0])
    chunk_size=max(1,900//width)
    placeholders='('+','.join('?' for _ in range(width))+')'
    for start in range(0,len(rows),chunk_size):
        chunk=rows[start:start+chunk_size]
        db.execute(prefix+' VALUES '+','.join([placeholders]*len(chunk))+suffix,
                   [value for row in chunk for value in row])


@contextmanager
def atomic():
    db = get_db()
    # Turso HTTP rejects BEGIN IMMEDIATE; plain BEGIN is enough for request-scoped writes.
    db.execute('BEGIN' if using_turso() else 'BEGIN IMMEDIATE')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise


def migrate_workflows(db, demo_seeded=False):
    def add_columns(table, definitions):
        existing = {r['name'] for r in db.execute(f'PRAGMA table_info({table})')}
        for name, definition in definitions.items():
            if name not in existing:
                db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
    add_columns('components', {'blocked': 'REAL NOT NULL DEFAULT 0', 'active': 'INTEGER NOT NULL DEFAULT 1'})
    add_columns('products', {'active': 'INTEGER NOT NULL DEFAULT 1', 'unit': "TEXT NOT NULL DEFAULT 'cái'",
                            'image_url': "TEXT NOT NULL DEFAULT ''", 'category': "TEXT NOT NULL DEFAULT ''", 'description': "TEXT NOT NULL DEFAULT ''"})
    add_columns('orders', {'bom_id': 'INTEGER REFERENCES boms(id)', 'production_by': 'INTEGER REFERENCES users(id)'})
    add_columns('boms', {'import_batch_id': 'INTEGER REFERENCES import_batches(id)'})
    db.execute('''CREATE TABLE IF NOT EXISTS sales_order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES orders(id),
        product_id INTEGER NOT NULL REFERENCES products(id), quantity INTEGER NOT NULL CHECK(quantity>0),
        unit_price INTEGER NOT NULL, bom_id INTEGER REFERENCES boms(id))''')
    db.execute('CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)')
    if not db.execute("SELECT 1 FROM schema_migrations WHERE name='order_snapshots_v2'").fetchone():
        # Legacy orders have no provable BOM version. Preserve existing snapshots;
        # never claim their version was the currently active BOM.
        for order in db.execute('SELECT * FROM orders').fetchall():
            db.execute('''INSERT INTO sales_order_items(order_id,product_id,quantity,unit_price,bom_id)
                VALUES(?,?,?,?,?)''', (order['id'], order['product_id'], order['quantity'],
                                      order['total'] // max(order['quantity'], 1), order['bom_id']))
            if not db.execute('SELECT 1 FROM order_component_requirements WHERE order_id=?', (order['id'],)).fetchone():
                for item in db.execute('SELECT * FROM product_components WHERE product_id=?', (order['product_id'],)).fetchall():
                    db.execute('''INSERT INTO order_component_requirements
                        (order_id,component_id,required,bom_quantity,available_at_check) VALUES(?,?,?,?,0)''',
                        (order['id'], item['component_id'], item['quantity']*order['quantity'], item['quantity']))
        if demo_seeded:
            db.execute("UPDATE orders SET bom_id=(SELECT id FROM boms b WHERE b.product_id=orders.product_id AND status='active')")
            db.execute('UPDATE sales_order_items SET bom_id=(SELECT bom_id FROM orders WHERE id=order_id)')
        db.execute("UPDATE orders SET material_status='reserved' WHERE status IN ('accepted','installing','testing','completed') AND material_status='unknown'")
        db.execute("INSERT INTO schema_migrations VALUES('order_snapshots_v2')")
    db.execute('CREATE INDEX IF NOT EXISTS reservation_by_order ON stock_reservation_transactions(order_id,component_id)')
    db.execute('CREATE INDEX IF NOT EXISTS import_rows_by_batch ON import_batch_rows(batch_id,row_number)')
    db.execute('CREATE INDEX IF NOT EXISTS waiting_orders ON orders(status,accepted_by)')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS component_sku_case_insensitive ON components(UPPER(sku))')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS product_sku_case_insensitive ON products(UPPER(sku))')
    # Enforce one active BOM at the database boundary as well as in the service.
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_bom ON boms(product_id) WHERE status='active'")
    if not db.execute("SELECT 1 FROM schema_migrations WHERE name='stock_ledger_v2'").fetchone():
        db.execute("""INSERT INTO stock_movements(component_id,quantity,movement_type,order_id,note,created_by,created_at)
            SELECT t.component_id,t.quantity,t.transaction_type,t.order_id,t.note,t.created_by,t.created_at
            FROM inventory_transactions t WHERE NOT EXISTS (SELECT 1 FROM stock_movements m
              WHERE m.component_id=t.component_id AND m.quantity=t.quantity AND m.movement_type=t.transaction_type
              AND m.created_at=t.created_at AND m.created_by=t.created_by AND m.order_id IS t.order_id
              AND m.note IS t.note)""")
        db.execute("INSERT INTO schema_migrations VALUES('stock_ledger_v2')")
    refresh_waiting_orders(db)


def save_draft(product_id, items, user_id, bom_id=None):
    parsed = [(int(cid), quantity(qty)) for cid, qty in items]
    if not parsed or len({cid for cid, _ in parsed}) != len(parsed):
        raise ValueError('BOM phải có linh kiện và không được trùng mã.')
    with atomic() as db:
        if not db.execute('SELECT id FROM products WHERE id=? AND active=1', (product_id,)).fetchone():
            raise ValueError('Sản phẩm không tồn tại hoặc đã ngừng sử dụng.')
        active_ids={row['id'] for row in db.execute('SELECT id FROM components WHERE active=1')}
        if not {cid for cid,_ in parsed}.issubset(active_ids):
            raise ValueError('Linh kiện không tồn tại hoặc đã ngừng sử dụng.')
        if bom_id:
            bom = db.execute("SELECT * FROM boms WHERE id=? AND product_id=? AND status='draft'", (bom_id, product_id)).fetchone()
            if not bom:
                raise ValueError('Chỉ được chỉnh sửa BOM nháp. Hãy tạo phiên bản mới.')
            db.execute('DELETE FROM bom_items WHERE bom_id=?', (bom_id,))
        else:
            version = db.execute('SELECT COALESCE(MAX(version),0)+1 FROM boms WHERE product_id=?', (product_id,)).fetchone()[0]
            db.execute('INSERT INTO boms(product_id,version,status,created_by,created_at) VALUES(?,?,?,?,?)',
                       (product_id, version, 'draft', user_id, now()))
            bom_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        insert_rows(db,'INSERT INTO bom_items(bom_id,component_id,quantity)', [(bom_id, cid, qty) for cid, qty in parsed])
        record_audit(user_id, 'bom_draft_saved', 'bom', bom_id)
    return bom_id


def activate_bom(bom_id, user_id):
    with atomic() as db:
        bom = db.execute("SELECT * FROM boms WHERE id=? AND status='draft'", (bom_id,)).fetchone()
        if not bom:
            raise ValueError('Chỉ được kích hoạt BOM nháp.')
        items = db.execute('''SELECT bi.*, c.active FROM bom_items bi JOIN components c ON c.id=bi.component_id
                              WHERE bom_id=?''', (bom_id,)).fetchall()
        product = db.execute('SELECT active FROM products WHERE id=?', (bom['product_id'],)).fetchone()
        if not product or not product['active'] or not items or any(not i['active'] for i in items):
            raise ValueError('BOM rỗng hoặc sản phẩm/linh kiện đã ngừng sử dụng.')
        db.execute("UPDATE boms SET status='archived' WHERE product_id=? AND status='active'", (bom['product_id'],))
        db.execute("UPDATE boms SET status='active' WHERE id=?", (bom_id,))
        db.execute('DELETE FROM product_components WHERE product_id=?', (bom['product_id'],))
        insert_rows(db,'INSERT INTO product_components', [(bom['product_id'], i['component_id'], i['quantity']) for i in items])
        record_audit(user_id, 'bom_activated', 'bom', bom_id)


def check_items(items):
    db = get_db()
    totals = defaultdict(Decimal)
    resolved, invalid = [], []
    components = {}
    for product_id, count in items:
        product_id, count = int(product_id), quantity(count, integer=True)
        product = db.execute('SELECT * FROM products WHERE id=? AND active=1', (product_id,)).fetchone()
        if not product:
            raise ValueError('Sản phẩm không tồn tại hoặc đã ngừng sử dụng.')
        bom = db.execute("SELECT id FROM boms WHERE product_id=? AND status='active'", (product_id,)).fetchone()
        rows = db.execute('''SELECT bi.*, c.* FROM bom_items bi JOIN components c ON c.id=bi.component_id
                             WHERE bi.bom_id=?''', (bom['id'],)).fetchall() if bom else []
        if not rows or any(not r['active'] for r in rows):
            invalid.append(product['sku'])
        resolved.append({'product_id': product_id, 'quantity': count, 'price': product['price'],
                         'bom_id': bom['id'] if bom and rows and all(r['active'] for r in rows) else None,
                         'name': product['name']})
        for row in rows:
            components[row['component_id']] = row
            totals[row['component_id']] += Decimal(str(row['quantity'])) * count
    if not resolved:
        raise ValueError('Đơn hàng phải có ít nhất một sản phẩm.')
    requirements = []
    for cid, required in sorted(totals.items()):
        component = components[cid]
        available = round(component['stock'] - component['reserved'] - component['blocked'], 6)
        required = float(required)
        requirements.append({'component_id': cid, 'sku': component['sku'], 'name': component['name'],
                             'unit': component['unit'], 'required': required, 'available': available,
                             'remaining': round(available - required, 6), 'shortage': max(0, round(required - available, 6))})
    status = 'unknown' if invalid else ('pending_material' if any(r['shortage'] > EPSILON for r in requirements) else 'pending_approval')
    return {'items': resolved, 'requirements': requirements, 'material_status': status, 'invalid_products': invalid}


def create_order(items, customer, user_id):
    if not customer.get('customer_name', '').strip():
        raise ValueError('Vui lòng nhập tên khách hàng.')
    with atomic() as db:
        result = check_items(items)
        code = 'DH-' + datetime.now().strftime('%y%m%d') + '-' + uuid4().hex[:12].upper()
        first = result['items'][0]
        total = sum(i['price'] * i['quantity'] for i in result['items'])
        if total>9_000_000_000_000_000_000:
            raise ValueError('Tổng giá trị đơn vượt giới hạn cho phép.')
        db.execute('''INSERT INTO orders(code,customer_name,customer_phone,delivery_address,note,
            product_id,quantity,total,status,material_status,created_by,created_at,bom_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (code, customer['customer_name'].strip(), customer.get('phone','').strip(), customer.get('address','').strip(),
             customer.get('note','').strip(), first['product_id'], sum(i['quantity'] for i in result['items']), total,
             'pending', result['material_status'], user_id, now(), first['bom_id']))
        oid = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        insert_rows(db,'''INSERT INTO sales_order_items(order_id,product_id,quantity,unit_price,bom_id)''',
                       [(oid, i['product_id'], i['quantity'], i['price'], i['bom_id']) for i in result['items']])
        insert_rows(db,'''INSERT INTO order_component_requirements
            (order_id,component_id,required,bom_quantity,available_at_check)''',
            [(oid, r['component_id'], r['required'], r['required'], r['available']) for r in result['requirements']])
        record_audit(user_id, 'order_created', 'order', oid)
    return oid


def order_materials(order_id, db=None):
    return (db or get_db()).execute('''SELECT r.*, c.sku,c.name,c.unit,c.active,
        ROUND(c.stock-c.reserved-c.blocked,6) available,
        MAX(0,ROUND(r.required-(c.stock-c.reserved-c.blocked),6)) shortage
        FROM order_component_requirements r JOIN components c ON c.id=r.component_id
        WHERE r.order_id=? ORDER BY c.id''', (order_id,)).fetchall()


def refresh_waiting_orders(db):
    # One statement avoids a query per waiting order on the HTTP database.
    db.execute("""UPDATE orders SET material_status=CASE
      WHEN NOT EXISTS (SELECT 1 FROM order_component_requirements r WHERE r.order_id=orders.id)
        OR EXISTS (SELECT 1 FROM order_component_requirements r JOIN components c ON c.id=r.component_id
                   WHERE r.order_id=orders.id AND c.active=0)
        OR (material_status='unknown' AND EXISTS
            (SELECT 1 FROM sales_order_items i WHERE i.order_id=orders.id AND i.bom_id IS NULL)) THEN 'unknown'
      WHEN EXISTS (SELECT 1 FROM order_component_requirements r JOIN components c ON c.id=r.component_id
                   WHERE r.order_id=orders.id AND r.required>ROUND(c.stock-c.reserved-c.blocked,6)+0.0000001)
        THEN 'pending_material' ELSE 'pending_approval' END
      WHERE status='pending' AND accepted_by IS NULL""")


def reserve_order(order_id, user_id):
    with atomic() as db:
        order = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
        if not order or order['status'] != 'pending' or order['accepted_by']:
            raise ValueError('Đơn đã được duyệt, đã hủy hoặc không còn chờ duyệt.')
        rows = order_materials(order_id, db)
        if not rows or order['material_status'] == 'unknown' or any(not r['active'] for r in rows):
            raise ValueError('Đơn chưa có BOM hợp lệ. Hãy tạo lại đơn sau khi hoàn thiện BOM.')
        if any(row['shortage'] > EPSILON for row in rows):
            raise ValueError('Không đủ vật tư khả dụng. Chưa giữ linh kiện nào cho đơn này.')
        changed = db.execute("""UPDATE components SET reserved=ROUND(reserved+
            (SELECT required FROM order_component_requirements r WHERE r.order_id=? AND r.component_id=components.id),6)
            WHERE active=1 AND id IN (SELECT component_id FROM order_component_requirements WHERE order_id=?)
            AND stock-reserved-blocked+?>=(SELECT required FROM order_component_requirements r
                                           WHERE r.order_id=? AND r.component_id=components.id)""",
            (order_id,order_id,EPSILON,order_id)).rowcount
        if changed != len(rows):
            raise ValueError('Tồn khả dụng đã thay đổi, chưa giữ vật tư.')
        db.execute("""INSERT INTO stock_reservation_transactions(order_id,component_id,quantity,transaction_type,created_by,created_at)
            SELECT order_id,component_id,required,'reserve',?,? FROM order_component_requirements WHERE order_id=?""",
            (user_id,now(),order_id))
        db.execute("""INSERT INTO stock_movements(component_id,quantity,movement_type,order_id,note,created_by,created_at)
            SELECT component_id,required,'reserve',order_id,'Duyệt và giữ vật tư',?,?
            FROM order_component_requirements WHERE order_id=?""",(user_id,now(),order_id))
        db.execute("UPDATE orders SET accepted_by=?,accepted_at=?,status='accepted',progress=20,material_status='reserved' WHERE id=?", (user_id, now(), order_id))
        record_audit(user_id, 'order_reserved', 'order', order_id)
        refresh_waiting_orders(db)


def cancel_order(order_id, user_id, role):
    with atomic() as db:
        order = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
        if not order or (role == 'sales' and order['created_by'] != user_id):
            raise ValueError('Không tìm thấy đơn hàng.')
        if order['status'] not in ('pending', 'accepted'):
            raise ValueError('Chỉ được hủy đơn chưa xuất vật tư sản xuất; đơn đã hủy không thể hủy lại.')
        if order['accepted_by']:
            verify_reservations(db,order_id)
            rows=order_materials(order_id,db)
            changed=db.execute("""UPDATE components SET reserved=ROUND(reserved-
                (SELECT required FROM order_component_requirements r WHERE r.order_id=? AND r.component_id=components.id),6)
                WHERE id IN (SELECT component_id FROM order_component_requirements WHERE order_id=?)
                AND reserved+?>=(SELECT required FROM order_component_requirements r WHERE r.order_id=? AND r.component_id=components.id)""",
                (order_id,order_id,EPSILON,order_id)).rowcount
            if changed!=len(rows):
                raise ValueError('Số liệu giữ kho không khớp. Không thể hủy đơn.')
            db.execute("""INSERT INTO stock_reservation_transactions(order_id,component_id,quantity,transaction_type,created_by,created_at)
                SELECT order_id,component_id,required,'release',?,? FROM order_component_requirements WHERE order_id=?""",(user_id,now(),order_id))
            db.execute("""INSERT INTO stock_movements(component_id,quantity,movement_type,order_id,note,created_by,created_at)
                SELECT component_id,required,'release',order_id,'Hủy đơn, giải phóng vật tư',?,?
                FROM order_component_requirements WHERE order_id=?""",(user_id,now(),order_id))
        db.execute("UPDATE orders SET status='cancelled',material_status='released' WHERE id=?", (order_id,))
        db.execute("UPDATE purchase_requests SET status='cancelled' WHERE order_id=? AND status='open'", (order_id,))
        record_audit(user_id, 'order_cancelled', 'order', order_id)
        refresh_waiting_orders(db)


def verify_reservations(db,order_id):
    rows=db.execute("""SELECT r.component_id,r.required,COALESCE(SUM(CASE
        WHEN t.transaction_type='reserve' THEN t.quantity ELSE -t.quantity END),0) allocated
        FROM order_component_requirements r LEFT JOIN stock_reservation_transactions t
        ON t.order_id=r.order_id AND t.component_id=r.component_id
        WHERE r.order_id=? GROUP BY r.component_id""",(order_id,)).fetchall()
    if not rows or any(abs(r['required']-r['allocated'])>EPSILON for r in rows):
        raise ValueError('Đơn chưa có sổ giữ kho khớp nhu cầu. Cần đối soát dữ liệu cũ trước khi xử lý.')


def issue_materials(db,order_id,user_id):
    verify_reservations(db,order_id)
    rows=order_materials(order_id,db)
    changed=db.execute("""UPDATE components SET
        stock=ROUND(stock-(SELECT required FROM order_component_requirements r WHERE r.order_id=? AND r.component_id=components.id),6),
        reserved=ROUND(reserved-(SELECT required FROM order_component_requirements r WHERE r.order_id=? AND r.component_id=components.id),6)
        WHERE id IN (SELECT component_id FROM order_component_requirements WHERE order_id=?)
        AND stock-blocked+?>=(SELECT required FROM order_component_requirements r WHERE r.order_id=? AND r.component_id=components.id)
        AND reserved+?>=(SELECT required FROM order_component_requirements r WHERE r.order_id=? AND r.component_id=components.id)""",
        (order_id,order_id,order_id,EPSILON,order_id,EPSILON,order_id)).rowcount
    if changed!=len(rows):
        raise ValueError('Không đủ vật tư đã giữ để xuất kho.')
    db.execute("""INSERT INTO stock_issues(order_id,component_id,quantity,created_by,created_at)
        SELECT order_id,component_id,required,?,? FROM order_component_requirements WHERE order_id=?""",(user_id,now(),order_id))
    db.execute("""INSERT INTO stock_movements(component_id,quantity,movement_type,order_id,note,created_by,created_at)
        SELECT component_id,required,'out',order_id,'Xuất kho sản xuất',?,?
        FROM order_component_requirements WHERE order_id=?""",(user_id,now(),order_id))
    db.execute("UPDATE orders SET material_status='issued' WHERE id=?",(order_id,))


def advance_order(order_id, status, user_id, role):
    stages = {'accepted': ('installing',45), 'installing': ('testing',70), 'testing': ('completed',90), 'completed': ('delivering',100)}
    with atomic() as db:
        order = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
        if not order or order['status'] not in stages or status != stages[order['status']][0]:
            raise ValueError('Chỉ được chuyển sang bước sản xuất kế tiếp.')
        if role=='technician' and order['production_by'] not in (None,user_id):
            raise ValueError('Đơn đã có Thợ phụ trách; chỉ người phụ trách được cập nhật sản xuất.')
        if status != 'installing' and role not in ('admin','technician'):
            raise ValueError('Chỉ Kỹ thuật / Thợ được cập nhật sản xuất.')
        if status == 'installing' and role not in ('admin','warehouse'):
            raise ValueError('Kho phải xuất vật tư trước khi bắt đầu sản xuất.')
        if status == 'installing':
            issue_materials(db,order_id,user_id)
        elif order['material_status']!='issued':
            raise ValueError('Đơn cũ chưa có phiếu xuất vật tư. Kho cần đối soát trước khi tiếp tục.')
        if role=='technician' and order['production_by'] is None:
            db.execute('UPDATE orders SET production_by=? WHERE id=?',(user_id,order_id))
        db.execute('UPDATE orders SET status=?,progress=? WHERE id=?', (status, stages[order['status']][1], order_id))
        record_audit(user_id,'order_progress','order',order_id,status)


def request_purchase(order_id, user_id):
    with atomic() as db:
        order = db.execute("SELECT id FROM orders WHERE id=? AND status='pending' AND material_status!='unknown'", (order_id,)).fetchone()
        if not order:
            raise ValueError('Đơn không còn chờ vật tư hoặc chưa có BOM hợp lệ.')
        if db.execute("SELECT id FROM purchase_requests WHERE order_id=? AND status='open'", (order_id,)).fetchone():
            raise ValueError('Đơn đã có đề nghị mua đang mở.')
        rows = [r for r in order_materials(order_id, db) if r['shortage'] > EPSILON]
        if not rows:
            raise ValueError('Đơn đã đủ vật tư, không cần mua thêm.')
        db.execute('INSERT INTO purchase_requests(order_id,created_by,created_at) VALUES(?,?,?)', (order_id,user_id,now()))
        rid = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        insert_rows(db,'INSERT INTO purchase_request_items', [(rid,r['component_id'],r['shortage']) for r in rows])
        record_audit(user_id,'purchase_request_created','purchase_request',rid)
    return rid


def receive_purchase(request_id, user_id):
    with atomic() as db:
        if not db.execute("SELECT id FROM purchase_requests WHERE id=? AND status='open'", (request_id,)).fetchone():
            raise ValueError('Đề nghị mua đã nhập, đã hủy hoặc không tồn tại.')
        db.execute("""UPDATE components SET stock=ROUND(stock+(SELECT quantity FROM purchase_request_items i
            WHERE i.request_id=? AND i.component_id=components.id),6)
            WHERE id IN (SELECT component_id FROM purchase_request_items WHERE request_id=?)""",(request_id,request_id))
        db.execute("""INSERT INTO stock_movements(component_id,quantity,movement_type,note,created_by,created_at)
            SELECT component_id,quantity,'in',?, ?, ? FROM purchase_request_items WHERE request_id=?""",
            (f'Nhập đề nghị mua #{request_id}',user_id,now(),request_id))
        db.execute("UPDATE purchase_requests SET status='received' WHERE id=?", (request_id,))
        refresh_waiting_orders(db)
        record_audit(user_id,'purchase_received','purchase_request',request_id)
