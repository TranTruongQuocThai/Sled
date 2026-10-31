from urllib.parse import urlparse
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for
from controllers.auth import login_required
from models.repository import INTEGRITY_ERRORS, get_db, product_capacity, product_requirements, record_audit, record_inventory_movement
from models.workflows import activate_bom, atomic, check_items, quantity, refresh_waiting_orders, save_draft
from models.excel_imports import commit_import, preview_import

inventory_bp=Blueprint('inventory',__name__,url_prefix='/inventory')
READ=['admin','sales','technician','warehouse','purchasing','accountant']
TECH=['admin','technician']
STOCK=['admin','warehouse']


@inventory_bp.route('/')
@login_required(READ)
def index():
    db=get_db()
    products=db.execute('SELECT * FROM products ORDER BY sku').fetchall()
    components=db.execute('''SELECT c.*,cc.name category_name FROM components c LEFT JOIN component_categories cc ON cc.id=c.category_id
        ORDER BY c.sku''').fetchall()
    all_components=db.execute('SELECT * FROM components WHERE active=1 ORDER BY sku').fetchall()
    versions=db.execute('''SELECT b.*,p.name product_name,p.sku product_sku,COUNT(i.component_id) item_count
        FROM boms b JOIN products p ON p.id=b.product_id LEFT JOIN bom_items i ON i.bom_id=b.id
        GROUP BY b.id ORDER BY b.id DESC''').fetchall()
    selected=db.execute('SELECT b.*,p.sku product_sku FROM boms b JOIN products p ON p.id=b.product_id WHERE b.id=?',(request.args.get('bom_id',type=int),)).fetchone()
    draft_items=db.execute('''SELECT bi.*,c.sku,c.name,c.unit,c.active FROM bom_items bi
        JOIN components c ON c.id=bi.component_id WHERE bi.bom_id=?''',(selected['id'],)).fetchall() if selected else []
    return render_template('inventory.html',products=products,components=components,all_components=all_components,
        categories=db.execute('SELECT * FROM component_categories ORDER BY name').fetchall(),versions=versions,
        selected=selected,draft_items=draft_items,product_capacity=product_capacity(),
        bom_products=db.execute('SELECT * FROM products WHERE active=1 ORDER BY sku').fetchall())


@inventory_bp.route('/products',methods=['POST'])
@inventory_bp.route('/products/<int:product_id>/edit',methods=['POST'])
@login_required(TECH)
def add_product(product_id=None):
    try:
        sku=request.form.get('sku','').strip().upper()
        name=request.form.get('name','').strip()
        price=int(request.form.get('price',''))
        unit=request.form.get('unit','cái').strip()
        image_url=request.form.get('image_url','').strip()
        if image_url and (urlparse(image_url).scheme not in ('https','http') or not urlparse(image_url).netloc):
            raise ValueError('Đường dẫn hình ảnh phải là URL http hoặc https hợp lệ.')
        if not sku or not name or not unit or not 0<=price<=1_000_000_000_000:
            raise ValueError('Mã, tên, đơn vị và giá sản phẩm không hợp lệ.')
        with atomic() as db:
            values=(sku,name,price,unit,request.form.get('category','').strip(),request.form.get('description','').strip(),image_url)
            if product_id:
                if db.execute('UPDATE products SET sku=?,name=?,price=?,unit=?,category=?,description=?,image_url=? WHERE id=?',values+(product_id,)).rowcount!=1:
                    raise ValueError('Sản phẩm không tồn tại.')
            else:
                db.execute('INSERT INTO products(sku,name,price,unit,category,description,image_url) VALUES(?,?,?,?,?,?,?)',values)
                product_id=db.execute('SELECT last_insert_rowid()').fetchone()[0]
            record_audit(session['user_id'],'product_saved','product',product_id)
        flash('Đã lưu sản phẩm.','success')
    except (ValueError,TypeError) as error:
        flash(str(error),'error')
    except INTEGRITY_ERRORS:
        flash('Mã sản phẩm đã tồn tại.','error')
    return redirect(url_for('inventory.index'))


@inventory_bp.route('/components',methods=['POST'])
@inventory_bp.route('/components/<int:component_id>/edit',methods=['POST'])
@login_required(STOCK)
def add_component(component_id=None):
    try:
        sku=request.form.get('sku','').strip().upper()
        name=request.form.get('name','').strip()
        unit=request.form.get('unit','').strip()
        minimum=request.form.get('min_stock','0')
        minimum=0 if minimum.strip() in ('0','0.0','') else quantity(minimum)
        category_id=request.form.get('category_id',type=int)
        if not sku or not name or not unit or not 0<=minimum<=1_000_000_000:
            raise ValueError('Dữ liệu linh kiện không hợp lệ.')
        with atomic() as db:
            if category_id and not db.execute('SELECT id FROM component_categories WHERE id=?',(category_id,)).fetchone():
                raise ValueError('Nhóm linh kiện không tồn tại.')
            if component_id:
                current=db.execute('SELECT unit,stock,reserved FROM components WHERE id=?',(component_id,)).fetchone()
                if not current:
                    raise ValueError('Linh kiện không tồn tại.')
                used=db.execute('SELECT 1 FROM bom_items WHERE component_id=?',(component_id,)).fetchone()
                if current['unit']!=unit and (used or current['stock'] or current['reserved']):
                    raise ValueError('Không được đổi đơn vị linh kiện đã có BOM hoặc tồn kho.')
                db.execute('UPDATE components SET sku=?,name=?,unit=?,min_stock=?,category_id=? WHERE id=?',
                           (sku,name,unit,minimum,category_id,component_id))
            else:
                initial=request.form.get('stock','0')
                initial=0 if str(initial).strip() in ('','0','0.0') else quantity(initial)
                db.execute('INSERT INTO components(sku,name,unit,min_stock,category_id,stock) VALUES(?,?,?,?,?,?)',
                           (sku,name,unit,minimum,category_id,initial))
                component_id=db.execute('SELECT last_insert_rowid()').fetchone()[0]
                if initial:
                    record_inventory_movement(component_id,initial,'in',session['user_id'],'Nhập tồn đầu khi tạo linh kiện')
            record_audit(session['user_id'],'component_saved','component',component_id)
        flash('Đã lưu linh kiện.','success')
    except (ValueError,TypeError) as error:
        flash(str(error),'error')
    except INTEGRITY_ERRORS:
        flash('Mã linh kiện đã tồn tại.','error')
    return redirect(url_for('inventory.index'))


@inventory_bp.route('/products/<int:entity_id>/toggle',methods=['POST'])
@login_required(TECH)
def toggle_product(entity_id):
    return toggle_entity('products',entity_id)


@inventory_bp.route('/components/<int:entity_id>/toggle',methods=['POST'])
@login_required(STOCK)
def toggle_component(entity_id):
    return toggle_entity('components',entity_id)


def toggle_entity(table,entity_id):
    with atomic() as db:
        if db.execute(f'UPDATE {table} SET active=1-active WHERE id=?',(entity_id,)).rowcount!=1:
            abort(404)
        record_audit(session['user_id'],'active_toggled',table,entity_id)
        refresh_waiting_orders(db)
    return redirect(url_for('inventory.index'))


@inventory_bp.route('/categories',methods=['POST'])
@login_required(STOCK)
def add_category():
    name=request.form.get('name','').strip()
    if not name:
        abort(400)
    try:
        with atomic() as db:
            db.execute('INSERT INTO component_categories(name) VALUES(?)',(name,))
    except INTEGRITY_ERRORS:
        flash('Nhóm đã tồn tại.','error')
    return redirect(url_for('inventory.index'))


@inventory_bp.route('/components/<int:component_id>/stock',methods=['POST'])
@login_required(STOCK)
def update_stock(component_id):
    try:
        stock=request.form['stock'].strip()
        blocked=request.form.get('blocked','0').strip()
        stock=0 if stock in ('0','0.0') else quantity(stock)
        blocked=0 if blocked in ('0','0.0','') else quantity(blocked)
        if not (0<=stock<=1_000_000_000 and 0<=blocked<=stock):
            raise ValueError('Tồn thực tế hoặc lượng bị khóa không hợp lệ.')
        with atomic() as db:
            item=db.execute('SELECT * FROM components WHERE id=?',(component_id,)).fetchone()
            if not item or stock+0.0000001<item['reserved']+blocked:
                raise ValueError('Tồn mới phải đủ cho lượng đã giữ và bị khóa.')
            db.execute('UPDATE components SET stock=?,blocked=? WHERE id=?',(stock,blocked,component_id))
            if stock!=item['stock']:
                record_inventory_movement(component_id,round(stock-item['stock'],6),'adjustment',session['user_id'],request.form.get('note','Kiểm kê tồn kho'))
            if blocked!=item['blocked']:
                record_audit(session['user_id'],'blocked_changed','component',component_id,f"{item['blocked']} -> {blocked}")
            refresh_waiting_orders(db)
        flash('Đã ghi nhận kiểm kê và lịch sử.','success')
    except (ValueError,TypeError,KeyError) as error:
        flash(str(error),'error')
    return redirect(url_for('inventory.index'))


@inventory_bp.route('/bom',methods=['POST'])
@login_required(TECH)
def save_bom():
    try:
        cids,qtys=request.form.getlist('component_id'),request.form.getlist('quantity')
        if len(cids)!=len(qtys):
            raise ValueError('Dữ liệu dòng BOM không hợp lệ.')
        bom_id=save_draft(int(request.form['product_id']),list(zip(cids,qtys)),session['user_id'],request.form.get('bom_id',type=int))
        flash('Đã lưu BOM nháp. Chỉ có hiệu lực sau khi kích hoạt.','success')
        return redirect(url_for('inventory.index',bom_id=bom_id))
    except (ValueError,KeyError) as error:
        flash(str(error),'error')
        return redirect(url_for('inventory.index'))


@inventory_bp.route('/boms/<int:bom_id>/activate',methods=['POST'])
@login_required(TECH)
def activate(bom_id):
    try:
        activate_bom(bom_id,session['user_id'])
        flash('Đã kích hoạt phiên bản BOM. Đơn cũ giữ nguyên vật tư.','success')
    except ValueError as error:
        flash(str(error),'error')
    return redirect(url_for('inventory.index',bom_id=bom_id))


@inventory_bp.route('/imports/<import_type>/preview',methods=['POST'])
@login_required(['admin','warehouse','technician'])
def import_preview(import_type):
    allowed=TECH if import_type=='bom' else STOCK
    if import_type not in ('components','bom') or session['role'] not in allowed:
        abort(403)
    try:
        batch_id,rows,errors=preview_import(request.files['file'],import_type,session['user_id'])
        return render_template('import_preview.html',batch_id=batch_id,import_type=import_type,rows=rows,error_count=errors)
    except (ValueError,KeyError,TypeError) as error:
        flash(str(error),'error')
        return redirect(url_for('inventory.index'))


@inventory_bp.route('/imports/<import_type>/<int:batch_id>/commit',methods=['POST'])
@login_required(['admin','warehouse','technician'])
def import_commit(import_type,batch_id):
    allowed=TECH if import_type=='bom' else STOCK
    if import_type not in ('components','bom') or session['role'] not in allowed:
        abort(403)
    try:
        bom_ids=commit_import(batch_id,import_type,session['user_id'],request.form.get('mode','create'))
        flash('Đã import. BOM được lưu nháp; tồn kho không thay đổi.','success')
        if bom_ids:
            return redirect(url_for('inventory.index',bom_id=bom_ids[0]))
    except ValueError as error:
        flash(str(error),'error')
    return redirect(url_for('inventory.index'))


@inventory_bp.route('/forecast')
@login_required(READ)
def forecast():
    try:
        product_id=int(request.args['product_id'])
        count=quantity(request.args.get('quantity',1),integer=True)
        result=check_items([(product_id,count)])
        if result['material_status']=='unknown':
            return jsonify(error='Sản phẩm chưa có BOM hợp lệ.',material_status='unknown'),422
        rows=product_requirements(product_id,count)
        if not rows:
            return jsonify(error='Sản phẩm chưa có BOM hiệu lực.',material_status='unknown'),422
        return jsonify([dict(x,shortage=x['remaining']<0) for x in rows])
    except (KeyError,ValueError,TypeError) as error:
        return jsonify(error=str(error)),400


@inventory_bp.route('/shortages')
@login_required(READ)
def shortages():
    rows=get_db().execute('''SELECT o.id,o.code,o.customer_name,c.sku,c.name component_name,r.required,
        ROUND(c.stock-c.reserved-c.blocked,6) available,ROUND(r.required-(c.stock-c.reserved-c.blocked),6) shortage
        FROM orders o JOIN order_component_requirements r ON r.order_id=o.id JOIN components c ON c.id=r.component_id
        WHERE o.status='pending' AND o.accepted_by IS NULL AND r.required>c.stock-c.reserved-c.blocked
        AND (?!='sales' OR o.created_by=?) ORDER BY o.id,c.sku''',(session['role'],session['user_id'])).fetchall()
    return jsonify([dict(row) for row in rows])


@inventory_bp.route('/products/<int:product_id>/bom-versions')
@login_required(READ)
def bom_versions(product_id):
    rows=get_db().execute('''SELECT b.*,COUNT(i.component_id) item_count FROM boms b
        LEFT JOIN bom_items i ON i.bom_id=b.id WHERE b.product_id=? GROUP BY b.id ORDER BY version DESC''',(product_id,)).fetchall()
    return jsonify([dict(row) for row in rows])


@inventory_bp.route('/audit-history')
@login_required(['admin'])
def audit_history():
    db=get_db()
    return render_template('audit_history.html',
        logs=db.execute('SELECT a.*,u.name operator_name FROM audit_logs a JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 200').fetchall(),
        batches=db.execute('SELECT b.*,u.name operator_name FROM import_batches b JOIN users u ON u.id=b.created_by ORDER BY b.id DESC LIMIT 100').fetchall())
