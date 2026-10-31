from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for
from controllers.auth import login_required
from models.repository import get_db, query_orders
from models.workflows import (advance_order, cancel_order, check_items, create_order,
                              order_materials, request_purchase, reserve_order, atomic)

orders_bp = Blueprint('orders', __name__, url_prefix='/orders')
VIEW_ROLES = ['admin','sales','technician','warehouse','purchasing','accountant']


def visible_order(order_id):
    order = get_db().execute('''SELECT o.*,p.name product_name,p.sku product_sku,u.name receiver_name,
        owner.name owner_name,producer.name production_name
        FROM orders o JOIN products p ON p.id=o.product_id LEFT JOIN users u ON u.id=o.accepted_by
        LEFT JOIN users owner ON owner.id=o.created_by LEFT JOIN users producer ON producer.id=o.production_by
        WHERE o.id=?''', (order_id,)).fetchone()
    if not order or (session['role']=='sales' and order['created_by']!=session['user_id']):
        abort(404)
    return order


def form_items():
    products, quantities = request.form.getlist('product_id'), request.form.getlist('quantity')
    if not products or len(products)!=len(quantities):
        raise ValueError('Danh sách sản phẩm và số lượng không hợp lệ.')
    return list(zip(products, quantities))


@orders_bp.route('/')
@login_required(VIEW_ROLES)
def index():
    return render_template('orders.html', orders=query_orders({'id':session['user_id'],'role':session['role']}))


@orders_bp.route('/new', methods=['GET','POST'])
@login_required(['admin','sales'])
def create():
    if request.method=='POST':
        try:
            oid = create_order(form_items(), request.form, session['user_id'])
            flash('Đã lưu đơn và chốt nhu cầu vật tư. Đơn chưa giữ kho.', 'success')
            return redirect(url_for('orders.detail',order_id=oid))
        except (ValueError, TypeError) as error:
            flash(str(error),'error')
    return render_template('order_form.html', products=get_db().execute('SELECT * FROM products WHERE active=1 ORDER BY sku').fetchall(), form=request.form)


@orders_bp.route('/check-stock', methods=['POST'])
@login_required(VIEW_ROLES)
def check_stock():
    try:
        return jsonify(check_items(form_items()))
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error), material_status='unknown'),400


@orders_bp.route('/<int:order_id>')
@login_required(VIEW_ROLES)
def detail(order_id):
    order = visible_order(order_id)
    items = get_db().execute('''SELECT i.*,p.sku,p.name,b.version FROM sales_order_items i
        JOIN products p ON p.id=i.product_id LEFT JOIN boms b ON b.id=i.bom_id WHERE order_id=?''',(order_id,)).fetchall()
    return render_template('order_detail.html',order=order,items=items,materials=order_materials(order_id))


@orders_bp.route('/<int:order_id>/edit',methods=['GET','POST'])
@login_required(['admin','sales'])
def edit(order_id):
    order=visible_order(order_id)
    if order['status']!='pending' or order['accepted_by']:
        flash('Chỉ sửa thông tin khách hàng khi đơn đang chờ duyệt.','error')
        return redirect(url_for('orders.detail',order_id=order_id))
    if request.method=='POST':
        name=request.form.get('customer_name','').strip()
        if not name:
            flash('Vui lòng nhập tên khách hàng.','error')
        else:
            with atomic() as db:
                changed=db.execute('''UPDATE orders SET customer_name=?,customer_phone=?,delivery_address=?,note=?
                    WHERE id=? AND status='pending' AND accepted_by IS NULL''',
                    (name,request.form.get('phone','').strip(),request.form.get('address','').strip(),request.form.get('note','').strip(),order_id)).rowcount
            flash('Đã cập nhật thông tin.' if changed else 'Trạng thái đơn đã thay đổi.','success' if changed else 'error')
            return redirect(url_for('orders.detail',order_id=order_id))
    return render_template('order_edit.html',order=order)


def perform(action, success):
    try:
        action()
        flash(success,'success')
    except ValueError as error:
        flash(str(error),'error')
    return redirect(url_for('orders.index'))


@orders_bp.route('/<int:order_id>/accept',methods=['POST'])
@login_required(['admin','warehouse'])
def accept(order_id):
    return perform(lambda: reserve_order(order_id,session['user_id']), 'Đã kiểm tra lại và giữ vật tư.')


@orders_bp.route('/<int:order_id>/cancel',methods=['POST'])
@login_required(['admin','sales'])
def cancel(order_id):
    visible_order(order_id)
    return perform(lambda: cancel_order(order_id,session['user_id'],session['role']), 'Đã hủy đơn và giải phóng vật tư đã giữ.')


@orders_bp.route('/<int:order_id>/purchase-request',methods=['POST'])
@login_required(['admin','purchasing'])
def create_purchase_request(order_id):
    return perform(lambda: request_purchase(order_id,session['user_id']), 'Đã tạo đề nghị mua cho các mã thiếu.')


@orders_bp.route('/<int:order_id>/progress',methods=['POST'])
@login_required(['admin','technician','warehouse'])
def update_progress(order_id):
    return perform(lambda: advance_order(order_id,request.form.get('status'),session['user_id'],session['role']), 'Đã cập nhật tiến độ sản xuất.')
