import sqlite3
from datetime import datetime
from flask import current_app, g
from werkzeug.security import generate_password_hash
import turso_serverless

INTEGRITY_ERRORS = (sqlite3.IntegrityError, turso_serverless.IntegrityError)


def get_db():
    if "db" not in g:
        turso_url = current_app.config.get("TURSO_DATABASE_URL")
        turso_token = current_app.config.get("TURSO_AUTH_TOKEN")
        if turso_url and turso_token:
            g.db = turso_serverless.connect(turso_url, auth_token=turso_token)
            g.db.row_factory = turso_serverless.Row
        else:
            g.db = sqlite3.connect(current_app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
        g.db.execute("PRAGMA busy_timeout=10000")
    return g.db


def record_inventory_movement(component_id, quantity, transaction_type, user_id, note=None, order_id=None):
    db = get_db()
    db.execute("""INSERT INTO stock_movements
      (component_id,quantity,movement_type,order_id,note,created_by,created_at)
      VALUES(?,?,?,?,?,?,?)""",
      (component_id, quantity, transaction_type, order_id, note, user_id,
       datetime.now().isoformat(timespec='seconds')))


def record_audit(user_id, action, entity_type, entity_id=None, details=None):
    get_db().execute("""INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details,created_at)
                        VALUES(?,?,?,?,?,?)""",
                     (user_id, action, entity_type, entity_id, details,
                      datetime.now().isoformat(timespec='seconds')))


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        db = get_db()
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','sales','technician','accountant','warehouse','purchasing'))
        );
        CREATE TABLE IF NOT EXISTS stock_movements (
          id INTEGER PRIMARY KEY AUTOINCREMENT, component_id INTEGER NOT NULL,
          quantity INTEGER NOT NULL, movement_type TEXT NOT NULL CHECK(movement_type IN ('in','out','reserve','release','adjustment')),
          order_id INTEGER, note TEXT, created_by INTEGER NOT NULL, created_at TEXT NOT NULL,
          FOREIGN KEY(component_id) REFERENCES components(id), FOREIGN KEY(order_id) REFERENCES orders(id),
          FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS components (
          id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
          unit TEXT NOT NULL DEFAULT 'cái', stock INTEGER NOT NULL DEFAULT 0,
          reserved INTEGER NOT NULL DEFAULT 0, min_stock INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS component_categories (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS commission_rules (
          threshold INTEGER PRIMARY KEY, rate REAL NOT NULL CHECK(rate >= 0 AND rate <= 100)
        );
        CREATE TABLE IF NOT EXISTS products (
          id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, price INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS product_components (
          product_id INTEGER NOT NULL, component_id INTEGER NOT NULL, quantity INTEGER NOT NULL,
          PRIMARY KEY(product_id, component_id), FOREIGN KEY(product_id) REFERENCES products(id),
          FOREIGN KEY(component_id) REFERENCES components(id)
        );
        CREATE TABLE IF NOT EXISTS boms (
          id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL, version INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','active','archived')),
          created_by INTEGER NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(product_id, version), FOREIGN KEY(product_id) REFERENCES products(id),
          FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS bom_items (
          bom_id INTEGER NOT NULL, component_id INTEGER NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0),
          PRIMARY KEY(bom_id, component_id), FOREIGN KEY(bom_id) REFERENCES boms(id),
          FOREIGN KEY(component_id) REFERENCES components(id)
        );
        CREATE TABLE IF NOT EXISTS orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, customer_name TEXT NOT NULL,
          customer_phone TEXT, delivery_address TEXT, note TEXT, product_id INTEGER NOT NULL,
          quantity INTEGER NOT NULL, total INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
          progress INTEGER NOT NULL DEFAULT 0, created_by INTEGER NOT NULL, created_at TEXT NOT NULL,
          accepted_by INTEGER, accepted_at TEXT,
          FOREIGN KEY(product_id) REFERENCES products(id), FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS inventory_transactions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, component_id INTEGER NOT NULL,
          quantity INTEGER NOT NULL, transaction_type TEXT NOT NULL CHECK(transaction_type IN ('in','out','reserve','release','adjustment')),
          order_id INTEGER,
          note TEXT, created_by INTEGER NOT NULL, created_at TEXT NOT NULL,
          FOREIGN KEY(component_id) REFERENCES components(id), FOREIGN KEY(order_id) REFERENCES orders(id),
          FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS order_component_requirements (
          order_id INTEGER NOT NULL, component_id INTEGER NOT NULL, required INTEGER NOT NULL,
          bom_quantity INTEGER NOT NULL, available_at_check INTEGER NOT NULL,
          PRIMARY KEY(order_id, component_id), FOREIGN KEY(order_id) REFERENCES orders(id),
          FOREIGN KEY(component_id) REFERENCES components(id)
        );
        CREATE TABLE IF NOT EXISTS stock_reservation_transactions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, component_id INTEGER NOT NULL,
          quantity INTEGER NOT NULL, transaction_type TEXT NOT NULL CHECK(transaction_type IN ('reserve','release')),
          created_by INTEGER NOT NULL, created_at TEXT NOT NULL,
          FOREIGN KEY(order_id) REFERENCES orders(id), FOREIGN KEY(component_id) REFERENCES components(id),
          FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS stock_issues (
          id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, component_id INTEGER NOT NULL,
          quantity INTEGER NOT NULL, created_by INTEGER NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(order_id, component_id), FOREIGN KEY(order_id) REFERENCES orders(id),
          FOREIGN KEY(component_id) REFERENCES components(id), FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS purchase_requests (
          id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, status TEXT NOT NULL DEFAULT 'open'
            CHECK(status IN ('open','received','cancelled')), created_by INTEGER NOT NULL, created_at TEXT NOT NULL,
          FOREIGN KEY(order_id) REFERENCES orders(id), FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS purchase_request_items (
          request_id INTEGER NOT NULL, component_id INTEGER NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0),
          PRIMARY KEY(request_id, component_id), FOREIGN KEY(request_id) REFERENCES purchase_requests(id),
          FOREIGN KEY(component_id) REFERENCES components(id)
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, action TEXT NOT NULL,
          entity_type TEXT NOT NULL, entity_id INTEGER, details TEXT, created_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS import_batches (
          id INTEGER PRIMARY KEY AUTOINCREMENT, import_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'preview',
          created_by INTEGER NOT NULL, created_at TEXT NOT NULL,
          FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS import_batch_rows (
          id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL, row_number INTEGER NOT NULL,
          payload TEXT NOT NULL, error TEXT, FOREIGN KEY(batch_id) REFERENCES import_batches(id)
        );
        CREATE TABLE IF NOT EXISTS urgent_purchase_requests (
          id INTEGER PRIMARY KEY AUTOINCREMENT, component_id INTEGER NOT NULL,
          requested_quantity INTEGER NOT NULL, note TEXT, status TEXT NOT NULL DEFAULT 'open',
          created_by INTEGER NOT NULL, created_at TEXT NOT NULL,
          handled_by INTEGER, handled_at TEXT,
          FOREIGN KEY(component_id) REFERENCES components(id), FOREIGN KEY(created_by) REFERENCES users(id),
          FOREIGN KEY(handled_by) REFERENCES users(id)
        );
        """)
        users_schema = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()['sql']
        if "'warehouse'" not in users_schema:
            db.execute("PRAGMA foreign_keys=OFF")
            db.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE users_admin_migration (
              id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
              password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','sales','technician','accountant','warehouse','purchasing'))
            );
            INSERT INTO users_admin_migration(id,name,email,password_hash,role)
              SELECT id,name,email,password_hash,CASE WHEN role='manager' THEN 'admin' ELSE role END FROM users;
            DROP TABLE users;
            ALTER TABLE users_admin_migration RENAME TO users;
            COMMIT;
            """)
            db.execute("PRAGMA foreign_keys=ON")
        db.execute('BEGIN IMMEDIATE')
        # Migration for databases created before the assignment workflow was added.
        order_columns = {row["name"] for row in db.execute("PRAGMA table_info(orders)")}
        if "accepted_by" not in order_columns:
            db.execute("ALTER TABLE orders ADD COLUMN accepted_by INTEGER")
        if "accepted_at" not in order_columns:
            db.execute("ALTER TABLE orders ADD COLUMN accepted_at TEXT")
        if "progress" not in order_columns:
            db.execute("ALTER TABLE orders ADD COLUMN progress INTEGER NOT NULL DEFAULT 0")
        component_columns = {row["name"] for row in db.execute("PRAGMA table_info(components)")}
        if "category_id" not in component_columns:
            db.execute("ALTER TABLE components ADD COLUMN category_id INTEGER")
        transaction_columns = {row["name"] for row in db.execute("PRAGMA table_info(inventory_transactions)")}
        if "order_id" not in transaction_columns:
            db.execute("ALTER TABLE inventory_transactions ADD COLUMN order_id INTEGER")
        order_columns = {row["name"] for row in db.execute("PRAGMA table_info(orders)")}
        if "material_status" not in order_columns:
            db.execute("ALTER TABLE orders ADD COLUMN material_status TEXT NOT NULL DEFAULT 'unknown'")
        demo_seeded = db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0 and app.config.get('SEED_DEMO', True)
        if demo_seeded:
            seed(db)
        seed_component_categories(db)
        seed_commission_rules(db)
        sync_active_boms(db)
        from models.workflows import migrate_workflows
        migrate_workflows(db, demo_seeded=demo_seeded)
        db.commit()


def seed(db):
    staff = [("Trần Quốc Huy", "manager@khoflow.local", "admin", "Manager123!"),
             ("Nguyễn Minh Anh", "sale@khoflow.local", "sales", "Sale"),
             ("Lê Gia Bảo", "tho@khoflow.local", "technician", "Thợ"),
             ("Phạm Thu Hà", "ketoan@khoflow.local", "accountant", "KeToan123!")]
    for name, email, role, password in staff:
        db.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)",
                   (name, email, generate_password_hash(password, method='pbkdf2:sha256'), role))
    parts = [("LK-001", "Khung nhôm 6061", "cái", 42, 0, 15), ("LK-002", "Bánh xe 80mm", "cái", 116, 0, 40),
             ("LK-003", "Motor DC 24V", "cái", 18, 0, 20), ("LK-004", "Bộ điều khiển M1", "bộ", 27, 0, 10),
             ("LK-005", "Pin lithium 24V", "bộ", 11, 0, 12)]
    db.executemany("INSERT INTO components(sku,name,unit,stock,reserved,min_stock) VALUES(?,?,?,?,?,?)", parts)
    db.execute("INSERT INTO products(sku,name,price) VALUES('SP-001','Xe đẩy tự hành S1',18000000)")
    ids = {row['sku']: row['id'] for row in db.execute("SELECT id,sku FROM components")}
    product_id = db.execute("SELECT id FROM products WHERE sku='SP-001'").fetchone()['id']
    db.executemany("INSERT INTO product_components(product_id,component_id,quantity) VALUES(?,?,?)",
                   [(product_id, ids['LK-001'], 1), (product_id, ids['LK-002'], 4), (product_id, ids['LK-003'], 2), (product_id, ids['LK-004'], 1), (product_id, ids['LK-005'], 1)])
    admin = db.execute("SELECT id FROM users WHERE role='admin'").fetchone()['id']
    sale = db.execute("SELECT id FROM users WHERE role='sales'").fetchone()['id']
    now = datetime.now().isoformat(timespec='seconds')
    db.executemany("""INSERT INTO inventory_transactions(component_id,quantity,transaction_type,note,created_by,created_at)
        SELECT id,stock,'in','Tồn đầu dữ liệu mẫu',?,? FROM components WHERE stock>0""", [(admin,now)])
    db.executemany("INSERT INTO orders(code,customer_name,customer_phone,delivery_address,note,product_id,quantity,total,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", [
      ('DH-24091','Công ty An Phát','0901000001','Quận 7, TP.HCM','',product_id,3,54000000,'pending',sale,now),
      ('DH-24087','Kho vận Đại Nam','0901000002','Bình Dương','',product_id,2,36000000,'pending',sale,now),
      ('DH-24084','Cơ khí Hoàng Long','0901000003','Đồng Nai','',product_id,5,90000000,'pending',admin,now)])


def seed_component_categories(db):
    defaults = ('Khung & cơ khí', 'Điện & điều khiển', 'Pin & năng lượng', 'Bánh xe & truyền động')
    db.executemany("INSERT OR IGNORE INTO component_categories(name) VALUES(?)", [(name,) for name in defaults])
    category_ids = {row['name']: row['id'] for row in db.execute("SELECT id,name FROM component_categories")}
    category_by_sku = {
        'LK-001': 'Khung & cơ khí', 'LK-002': 'Bánh xe & truyền động',
        'LK-003': 'Điện & điều khiển', 'LK-004': 'Điện & điều khiển', 'LK-005': 'Pin & năng lượng',
    }
    for sku, category in category_by_sku.items():
        db.execute("UPDATE components SET category_id=? WHERE sku=? AND category_id IS NULL",
                   (category_ids[category], sku))


def seed_commission_rules(db):
    rules = ((0, 1), (200_000_000, 3), (500_000_000, 5))
    db.executemany("INSERT OR IGNORE INTO commission_rules(threshold,rate) VALUES(?,?)", rules)


def query_orders(user):
    sql = """SELECT o.*, COALESCE((SELECT GROUP_CONCAT(p2.name || ' ? ' || i.quantity, ', ') FROM sales_order_items i JOIN products p2 ON p2.id=i.product_id WHERE i.order_id=o.id),p.name) product_name, u.name owner_name, receiver.name receiver_name, producer.name production_name FROM orders o
             JOIN products p ON p.id=o.product_id JOIN users u ON u.id=o.created_by
             LEFT JOIN users receiver ON receiver.id=o.accepted_by
             LEFT JOIN users producer ON producer.id=o.production_by"""
    args = []
    if user['role'] == 'sales':
        sql += " WHERE o.created_by=?"; args.append(user['id'])
    return get_db().execute(sql + " ORDER BY o.id DESC", args).fetchall()


def product_requirements(product_id, order_quantity):
    return get_db().execute("""SELECT c.*, bi.quantity AS per_product,
      bi.quantity * ? AS required, (c.stock-c.reserved-c.blocked) AS available,
      (c.stock-c.reserved-c.blocked-(bi.quantity * ?)) AS remaining
      FROM boms b JOIN bom_items bi ON bi.bom_id=b.id JOIN components c ON c.id=bi.component_id
      WHERE b.product_id=? AND b.status='active' AND c.active=1 AND EXISTS (SELECT 1 FROM products p WHERE p.id=b.product_id AND p.active=1)""",
      (order_quantity, order_quantity, product_id)).fetchall()


def build_order_requirements(product_id, order_quantity):
    """Return material requirements with a point-in-time availability check."""
    return get_db().execute("""SELECT c.id component_id, c.sku, c.name, c.unit,
      bi.quantity AS bom_quantity, bi.quantity * ? AS required,
      (c.stock-c.reserved-c.blocked) AS available,
      (c.stock-c.reserved-c.blocked-(bi.quantity * ?)) AS remaining
      FROM boms b JOIN bom_items bi ON bi.bom_id=b.id JOIN components c ON c.id=bi.component_id
      WHERE b.product_id=? AND b.status='active' AND c.active=1 AND EXISTS (SELECT 1 FROM products p WHERE p.id=b.product_id AND p.active=1) ORDER BY c.sku""",
      (order_quantity, order_quantity, product_id)).fetchall()


def sync_active_boms(db):
    """Backfill one active version for legacy product_components rows."""
    products = db.execute('SELECT id FROM products').fetchall()
    now = datetime.now().isoformat(timespec='seconds')
    creator = db.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
    if not creator:
        return
    for product in products:
        active = db.execute("SELECT id FROM boms WHERE product_id=? LIMIT 1", (product['id'],)).fetchone()
        if active:
            continue
        items = db.execute('SELECT component_id, quantity FROM product_components WHERE product_id=?',
                           (product['id'],)).fetchall()
        if not items:
            continue
        db.execute("INSERT OR IGNORE INTO boms(product_id,version,status,created_by,created_at) VALUES(?,?,?,?,?)",
                   (product['id'], 1, 'active', creator['id'], now))
        bom = db.execute("SELECT id FROM boms WHERE product_id=? AND version=1", (product['id'],)).fetchone()
        db.executemany("INSERT OR IGNORE INTO bom_items(bom_id,component_id,quantity) VALUES(?,?,?)",
                       [(bom['id'], item['component_id'], item['quantity']) for item in items])


def product_capacity():
    """Return the maximum buildable quantity for every product based on available components."""
    return get_db().execute("""SELECT p.id, p.sku, p.name, p.price,
      CASE WHEN MIN(COALESCE(c.active,0))=0 THEN 0
      ELSE MAX(0,COALESCE(MIN(CAST(ROUND((c.stock-c.reserved-c.blocked)*1.0/bi.quantity,6) AS INTEGER)),0)) END AS buildable,
      GROUP_CONCAT(CASE WHEN (c.stock - c.reserved - c.blocked) < bi.quantity THEN c.name END) AS shortages
      FROM products p LEFT JOIN boms b ON b.product_id=p.id AND b.status='active'
      LEFT JOIN bom_items bi ON bi.bom_id=b.id
      LEFT JOIN components c ON c.id=bi.component_id
      WHERE p.active=1 GROUP BY p.id ORDER BY p.name""").fetchall()
