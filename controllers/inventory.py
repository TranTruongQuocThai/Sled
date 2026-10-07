import sqlite3
from datetime import datetime
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for
from controllers.auth import login_required
from models.repository import get_db, product_capacity, product_requirements

inventory_bp=Blueprint('inventory',__name__,url_prefix='/inventory')
@inventory_bp.route('/')
@login_required(['admin', 'technician', 'accountant'])
def index():
    db = get_db()
    active_section = request.args.get('section', 'products')
    if active_section not in ('products', 'components'):
        active_section = 'products'
    if session['role'] == 'technician':
        active_section = 'products'
    if session['role'] == 'accountant':
        active_section = 'components'
    categories = db.execute("""SELECT cc.id, cc.name, COUNT(c.id) AS component_count
                               FROM component_categories cc LEFT JOIN components c ON c.category_id=cc.id
                               GROUP BY cc.id ORDER BY cc.name""").fetchall()
    selected_category = request.args.get('category', type=int)
    sql = """SELECT c.*, COALESCE(cc.name, 'Chưa phân loại') AS category_name
             FROM components c LEFT JOIN component_categories cc ON cc.id=c.category_id"""
    args = []
    if selected_category:
        sql += " WHERE c.category_id=?"; args.append(selected_category)
    components = db.execute(sql + ' ORDER BY c.sku', args).fetchall()
    all_components = db.execute("""SELECT c.*, COALESCE(cc.name, 'Chưa phân loại') AS category_name
                                   FROM components c LEFT JOIN component_categories cc ON cc.id=c.category_id
                                   ORDER BY c.sku""").fetchall()
    products = db.execute('SELECT * FROM products ORDER BY name').fetchall()
    bom = db.execute("""SELECT pc.product_id, p.name product_name, c.name component_name, c.sku, c.unit, pc.quantity
                        FROM product_components pc JOIN products p ON p.id=pc.product_id
                        JOIN components c ON c.id=pc.component_id ORDER BY p.name, c.sku""").fetchall()
    return render_template('inventory.html', components=components, all_components=all_components,
                           products=products, bom=bom, categories=categories,
                           selected_category=selected_category, active_section=active_section,
                           product_capacity=product_capacity())


@inventory_bp.route('/components', methods=['POST'])
@login_required(['admin', 'accountant'])
def add_component():
    sku = request.form['sku'].strip().upper()
    name = request.form['name'].strip()
    try:
        stock = int(request.form['stock'])
        min_stock = int(request.form.get('min_stock', 0))
        category_id = int(request.form['category_id'])
        category = get_db().execute('SELECT id FROM component_categories WHERE id=?', (category_id,)).fetchone()
        if not sku or not name or stock < 0 or min_stock < 0 or not category:
            raise ValueError
        get_db().execute('INSERT INTO components(sku,name,unit,stock,reserved,min_stock,category_id) VALUES(?,?,?,?,?,?,?)',
                         (sku, name, request.form['unit'].strip() or 'cái', stock, 0, min_stock, category_id))
        if stock > 0:
            component_id = get_db().execute('SELECT id FROM components WHERE sku=?', (sku,)).fetchone()['id']
            get_db().execute("""INSERT INTO inventory_transactions(component_id,quantity,transaction_type,note,created_by,created_at)
                              VALUES(?,?,?,?,?,?)""",
                           (component_id, stock, 'in', 'Tồn đầu khi tạo vật tư', session['user_id'], datetime.now().isoformat(timespec='seconds')))
        get_db().commit()
        flash('Đã thêm linh kiện mới vào kho.', 'success')
    except (ValueError, KeyError):
        flash('Dữ liệu linh kiện chưa hợp lệ.', 'error')
    except Exception:
        flash('Mã linh kiện đã tồn tại hoặc không thể lưu.', 'error')
    return redirect(url_for('accounting.index'))


@inventory_bp.route('/products', methods=['POST'])
@login_required(['admin', 'technician'])
def add_product():
    sku = request.form.get('sku', '').strip().upper()
    name = request.form.get('name', '').strip()
    try:
        price = int(request.form.get('price', ''))
        if not sku or not name or price < 0:
            raise ValueError
        get_db().execute('INSERT INTO products(sku,name,price) VALUES(?,?,?)', (sku, name, price))
        get_db().commit()
        flash('Đã thêm mặt hàng sản xuất mới.', 'success')
    except (ValueError, TypeError):
        flash('Mã, tên và giá mặt hàng chưa hợp lệ.', 'error')
    except sqlite3.IntegrityError:
        flash('Mã mặt hàng đã tồn tại.', 'error')
    return redirect(url_for('inventory.index', section='products'))


@inventory_bp.route('/categories', methods=['POST'])
@login_required(['admin', 'accountant'])
def add_category():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Vui lòng nhập tên loại vật tư.', 'error')
    else:
        try:
            get_db().execute('INSERT INTO component_categories(name) VALUES(?)', (name,))
            get_db().commit()
            flash('Đã thêm loại vật tư mới.', 'success')
        except sqlite3.IntegrityError:
            flash('Loại vật tư này đã tồn tại.', 'error')
    return redirect(url_for('accounting.index'))


@inventory_bp.route('/components/<int:component_id>/stock', methods=['POST'])
@login_required(['admin', 'accountant'])
def update_stock(component_id):
    component = get_db().execute('SELECT name,reserved FROM components WHERE id=?', (component_id,)).fetchone()
    if not component:
        abort(404)
    try:
        stock = int(request.form['stock'])
        if stock < component['reserved']:
            raise ValueError
        get_db().execute('UPDATE components SET stock=? WHERE id=?', (stock, component_id))
        get_db().commit()
        flash(f"Đã cập nhật tồn kho: {component['name']}.", 'success')
    except (ValueError, TypeError):
        flash(f"Tồn kho mới không thể thấp hơn số lượng đã giữ ({component['reserved']}).", 'error')
    return redirect(url_for('accounting.index'))


@inventory_bp.route('/bom', methods=['POST'])
@login_required(['admin', 'technician'])
def save_bom():
    try:
        product_id = int(request.form['product_id'])
        component_id = int(request.form['component_id'])
        quantity = int(request.form['quantity'])
        if quantity < 1:
            raise ValueError
        db = get_db()
        db.execute("""INSERT INTO product_components(product_id,component_id,quantity) VALUES(?,?,?)
                      ON CONFLICT(product_id,component_id) DO UPDATE SET quantity=excluded.quantity""",
                   (product_id, component_id, quantity))
        db.commit()
        flash('Đã lưu định mức linh kiện cho sản phẩm.', 'success')
    except (ValueError, KeyError):
        flash('Số lượng định mức phải lớn hơn 0.', 'error')
    return redirect(url_for('inventory.index', section='products'))


@inventory_bp.route('/urgent-request', methods=['POST'])
@login_required(['technician'])
def urgent_request():
    try:
        component_id = int(request.form['component_id'])
        quantity = int(request.form['quantity'])
        if quantity < 1 or not get_db().execute('SELECT id FROM components WHERE id=?', (component_id,)).fetchone():
            raise ValueError
        get_db().execute("""INSERT INTO urgent_purchase_requests(component_id,requested_quantity,note,created_by,created_at)
                         VALUES(?,?,?,?,?)""", (component_id, quantity, request.form.get('note', '').strip(),
                           session['user_id'], datetime.now().isoformat(timespec='seconds')))
        get_db().commit()
        flash('Đã gửi yêu cầu nhập linh kiện gấp cho Kế toán.', 'success')
    except (ValueError, KeyError):
        flash('Vui lòng chọn linh kiện và số lượng hợp lệ.', 'error')
    return redirect(url_for('inventory.index'))

@inventory_bp.route('/forecast')
@login_required(['admin', 'technician'])
def forecast():
    quantity=max(1, int(request.args.get('quantity',1))); product_id=int(request.args.get('product_id',1))
    return jsonify([dict(x) | {'shortage': x['remaining'] < 0} for x in product_requirements(product_id,quantity)])
