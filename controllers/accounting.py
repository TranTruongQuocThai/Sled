from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from controllers.auth import login_required
from models.repository import get_db, record_inventory_movement, record_audit
from models.workflows import atomic, quantity, receive_purchase, refresh_waiting_orders

accounting_bp=Blueprint('accounting',__name__,url_prefix='/accounting')


@accounting_bp.route('/')
@login_required(['admin','warehouse','purchasing','accountant'])
def index():
    db=get_db()
    purchases=db.execute('''SELECT pr.*,o.code,GROUP_CONCAT(c.sku || ' × ' || i.quantity, ', ') item_summary
        FROM purchase_requests pr LEFT JOIN orders o ON o.id=pr.order_id JOIN purchase_request_items i ON i.request_id=pr.id
        JOIN components c ON c.id=i.component_id GROUP BY pr.id ORDER BY pr.id DESC''').fetchall()
    transactions=db.execute('''SELECT m.*,c.sku,c.name,c.unit,u.name operator_name FROM stock_movements m
        JOIN components c ON c.id=m.component_id JOIN users u ON u.id=m.created_by ORDER BY m.id DESC LIMIT 100''').fetchall()
    shortages=db.execute('''SELECT o.id,o.code,c.sku,c.name,r.required,ROUND(c.stock-c.reserved-c.blocked,6) available,
        ROUND(r.required-(c.stock-c.reserved-c.blocked),6) shortage FROM orders o
        JOIN order_component_requirements r ON r.order_id=o.id JOIN components c ON c.id=r.component_id
        WHERE o.status='pending' AND o.accepted_by IS NULL AND r.required>c.stock-c.reserved-c.blocked
        ORDER BY o.id,c.id''').fetchall()
    purchase_items={}
    for item in db.execute('''SELECT i.*,c.sku,c.name,c.unit FROM purchase_request_items i
        JOIN components c ON c.id=i.component_id ORDER BY i.request_id,c.sku'''):
        purchase_items.setdefault(item['request_id'],[]).append(item)
    return render_template('accounting.html',components=db.execute('SELECT * FROM components WHERE active=1 ORDER BY sku').fetchall(),
                           purchases=purchases,purchase_items=purchase_items,transactions=transactions,shortages=shortages)


@accounting_bp.route('/stock-entry',methods=['POST'])
@login_required(['admin','warehouse'])
def stock_entry():
    try:
        cid=int(request.form['component_id'])
        count=quantity(request.form['quantity'])
        with atomic() as db:
            if db.execute('UPDATE components SET stock=ROUND(stock+?,6) WHERE id=? AND active=1',(count,cid)).rowcount!=1:
                raise ValueError('Linh kiện không tồn tại hoặc đã ngừng sử dụng.')
            record_inventory_movement(cid,count,'in',session['user_id'],request.form.get('note','').strip())
            refresh_waiting_orders(db)
        flash('Đã nhập kho và kiểm tra lại các đơn chờ; chưa tự giữ vật tư.','success')
    except (ValueError,KeyError) as error:
        flash(str(error),'error')
    return redirect(url_for('accounting.index'))


@accounting_bp.route('/purchase-requests/<int:request_id>/receive',methods=['POST'])
@login_required(['admin','warehouse'])
def receive_purchase_request(request_id):
    try:
        receive_purchase(request_id,session['user_id'])
        flash('Đã nhập đủ vật tư theo đề nghị và kiểm tra lại đơn chờ.','success')
    except ValueError as error:
        flash(str(error),'error')
    return redirect(url_for('accounting.index'))


@accounting_bp.route('/purchase-requests/<int:request_id>/cancel',methods=['POST'])
@login_required(['admin','purchasing'])
def cancel_purchase_request(request_id):
    with atomic() as db:
        changed=db.execute("UPDATE purchase_requests SET status='cancelled' WHERE id=? AND status='open'",(request_id,)).rowcount
        if changed:
            record_audit(session['user_id'],'purchase_cancelled','purchase_request',request_id)
    flash('Đã hủy đề nghị mua.' if changed else 'Phiếu đã đóng hoặc không tồn tại.','success' if changed else 'error')
    return redirect(url_for('accounting.index'))
