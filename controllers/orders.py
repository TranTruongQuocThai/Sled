from datetime import datetime
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from controllers.auth import login_required
from models.repository import get_db, product_requirements, query_orders

orders_bp=Blueprint('orders',__name__,url_prefix='/orders')


def get_sales_order(order_id):
    """Return an order only when it belongs to the logged-in sales user."""
    return get_db().execute("""SELECT o.*, p.name AS product_name, p.sku AS product_sku,
                              receiver.name AS receiver_name
                              FROM orders o JOIN products p ON p.id=o.product_id
                              LEFT JOIN users receiver ON receiver.id=o.accepted_by
                              WHERE o.id=? AND o.created_by=?""",
                           (order_id, session['user_id'])).fetchone()
@orders_bp.route('/')
@login_required(['admin','sales','technician'])
def index(): return render_template('orders.html', orders=query_orders({'id':session['user_id'],'role':session['role']}))

@orders_bp.route('/new', methods=['GET','POST'])
@login_required(['admin','sales'])
def create():
    db=get_db(); products=db.execute('SELECT * FROM products').fetchall()
    if request.method=='POST':
        product_id=int(request.form['product_id']); quantity=int(request.form['quantity'])
        if quantity < 1: abort(400)
        shortages=[p for p in product_requirements(product_id,quantity) if p['remaining'] < 0]
        if shortages:
            flash('Không đủ tồn kho để tạo đơn: '+', '.join(x['name'] for x in shortages), 'error')
            return render_template('order_form.html', products=products, form=request.form, forecast=product_requirements(product_id,quantity))
        product=db.execute('SELECT * FROM products WHERE id=?',(product_id,)).fetchone()
        code='DH-'+datetime.now().strftime('%y%m%d%H%M%S')
        db.execute("""INSERT INTO orders(code,customer_name,customer_phone,delivery_address,note,product_id,quantity,total,status,created_by,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(code,request.form['customer_name'],request.form.get('phone',''),request.form.get('address',''),request.form.get('note',''),product_id,quantity,product['price']*quantity,'pending',session['user_id'],datetime.now().isoformat(timespec='seconds')))
        db.execute("""UPDATE components SET reserved=reserved + (
          SELECT quantity * ? FROM product_components pc WHERE pc.component_id=components.id AND pc.product_id=?
          ) WHERE id IN (SELECT component_id FROM product_components WHERE product_id=?)""", (quantity, product_id, product_id))
        db.commit(); flash('Đã tạo đơn hàng '+code, 'success'); return redirect(url_for('orders.index'))
    return render_template('order_form.html', products=products, form={}, forecast=[])


@orders_bp.route('/<int:order_id>')
@login_required(['sales'])
def detail(order_id):
    order = get_sales_order(order_id)
    if not order:
        abort(404)
    return render_template('order_detail.html', order=order)


@orders_bp.route('/<int:order_id>/edit', methods=['GET', 'POST'])
@login_required(['sales'])
def edit(order_id):
    order = get_sales_order(order_id)
    if not order:
        abort(404)
    if order['accepted_by']:
        flash('Đơn đã được xưởng tiếp nhận nên không thể chỉnh sửa.', 'error')
        return redirect(url_for('orders.detail', order_id=order_id))
    if request.method == 'POST':
        customer_name = request.form.get('customer_name', '').strip()
        if not customer_name:
            flash('Vui lòng nhập tên khách hàng.', 'error')
        else:
            get_db().execute("""UPDATE orders SET customer_name=?, customer_phone=?,
                                delivery_address=?, note=? WHERE id=? AND created_by=? AND accepted_by IS NULL""",
                             (customer_name, request.form.get('phone', '').strip(),
                              request.form.get('address', '').strip(), request.form.get('note', '').strip(),
                              order_id, session['user_id']))
            get_db().commit()
            flash('Đã cập nhật thông tin đơn hàng.', 'success')
            return redirect(url_for('orders.detail', order_id=order_id))
    return render_template('order_edit.html', order=order)


@orders_bp.route('/<int:order_id>/accept', methods=['POST'])
@login_required(['admin', 'technician'])
def accept(order_id):
    db = get_db()
    order = db.execute('SELECT id, accepted_by FROM orders WHERE id=?', (order_id,)).fetchone()
    if not order:
        abort(404)
    if order['accepted_by']:
        flash('Đơn hàng này đã được một người khác nhận.', 'error')
    else:
        db.execute("UPDATE orders SET accepted_by=?, accepted_at=?, status='accepted', progress=20 WHERE id=? AND accepted_by IS NULL",
                   (session['user_id'], datetime.now().isoformat(timespec='seconds'), order_id))
        db.commit()
        flash('Bạn đã nhận đơn hàng thành công.', 'success')
    return redirect(url_for('orders.index'))


@orders_bp.route('/<int:order_id>/progress', methods=['POST'])
@login_required(['admin', 'technician'])
def update_progress(order_id):
    stages = {
        'accepted': ('Nhận đơn', 20),
        'installing': ('Đang lắp đặt', 45),
        'testing': ('Đang kiểm thử', 70),
        'completed': ('Hoàn thành', 90),
        'delivering': ('Giao hàng', 100),
    }
    stage_order = list(stages)
    status = request.form.get('status')
    order = get_db().execute('SELECT accepted_by FROM orders WHERE id=?', (order_id,)).fetchone()
    if not order:
        abort(404)
    if status not in stages:
        flash('Trạng thái tiến độ không hợp lệ.', 'error')
    elif session['role'] == 'technician' and order['accepted_by'] != session['user_id']:
        flash('Thợ chỉ có thể cập nhật đơn hàng do chính mình nhận.', 'error')
    elif not order['accepted_by']:
        flash('Cần nhận đơn hàng trước khi cập nhật tiến độ.', 'error')
    else:
        current = get_db().execute('SELECT status FROM orders WHERE id=?', (order_id,)).fetchone()['status']
        # A completed step is immutable: only the immediate next step is accepted.
        current_index = stage_order.index(current) if current in stage_order else -1
        if current_index == len(stage_order) - 1 or status != stage_order[current_index + 1]:
            flash('Tiến độ chỉ có thể chuyển sang bước kế tiếp, không thể quay lại.', 'error')
        else:
            get_db().execute('UPDATE orders SET status=?, progress=? WHERE id=?', (status, stages[status][1], order_id))
            get_db().commit()
            flash('Đã cập nhật tiến độ: ' + stages[status][0] + '.', 'success')
    return redirect(url_for('orders.index'))
