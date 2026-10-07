from datetime import datetime
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from controllers.auth import login_required
from models.repository import get_db

accounting_bp = Blueprint('accounting', __name__, url_prefix='/accounting')

@accounting_bp.route('/')
@login_required(['admin', 'accountant'])
def index():
    db = get_db()
    components = db.execute('SELECT * FROM components ORDER BY sku').fetchall()
    categories = db.execute('SELECT id, name FROM component_categories ORDER BY name').fetchall()
    low = [item for item in components if item['stock'] - item['reserved'] <= item['min_stock']]
    transactions = db.execute("""SELECT t.*, c.sku, c.name component_name, c.unit, u.name operator_name
      FROM inventory_transactions t JOIN components c ON c.id=t.component_id
      JOIN users u ON u.id=t.created_by ORDER BY t.id DESC LIMIT 30""").fetchall()
    invoices = db.execute("""SELECT o.code,o.customer_name,o.total,o.status,o.created_at,p.name product_name,u.name owner_name
      FROM orders o JOIN products p ON p.id=o.product_id JOIN users u ON u.id=o.created_by ORDER BY o.id DESC LIMIT 30""").fetchall()
    summary = db.execute('SELECT COALESCE(SUM(total),0) AS revenue, COUNT(*) AS invoice_count FROM orders').fetchone()
    monthly_revenue = db.execute("""SELECT substr(created_at,1,7) month, COALESCE(SUM(total),0) total, COUNT(*) count
                                   FROM orders GROUP BY substr(created_at,1,7) ORDER BY month DESC LIMIT 6""").fetchall()
    requests = db.execute("""SELECT r.*, c.sku, c.name component_name, c.unit, u.name requester_name
                            FROM urgent_purchase_requests r JOIN components c ON c.id=r.component_id
                            JOIN users u ON u.id=r.created_by WHERE r.status='open' ORDER BY r.id DESC""").fetchall()
    return render_template('accounting.html', components=components, categories=categories, low=low, transactions=transactions,
                           invoices=invoices, summary=summary, monthly_revenue=monthly_revenue, urgent_requests=requests)

@accounting_bp.route('/stock-entry', methods=['POST'])
@login_required(['admin', 'accountant'])
def stock_entry():
    try:
        component_id = int(request.form['component_id'])
        quantity = int(request.form['quantity'])
        note = request.form.get('note', '').strip()
        if quantity <= 0:
            raise ValueError
        db = get_db()
        component = db.execute('SELECT name FROM components WHERE id=?', (component_id,)).fetchone()
        if not component:
            raise ValueError
        db.execute('UPDATE components SET stock=stock+? WHERE id=?', (quantity, component_id))
        db.execute("INSERT INTO inventory_transactions(component_id,quantity,transaction_type,note,created_by,created_at) VALUES(?,?,?,?,?,?)",
                   (component_id, quantity, 'in', note, session['user_id'], datetime.now().isoformat(timespec='seconds')))
        db.commit()
        flash(f"Đã nhập {quantity} vật tư: {component['name']}.", 'success')
    except (ValueError, KeyError):
        flash('Số lượng nhập phải lớn hơn 0.', 'error')
    return redirect(url_for('accounting.index'))


@accounting_bp.route('/urgent-requests/<int:request_id>/complete', methods=['POST'])
@login_required(['admin', 'accountant'])
def complete_urgent_request(request_id):
    db = get_db()
    item = db.execute("SELECT id FROM urgent_purchase_requests WHERE id=? AND status='open'", (request_id,)).fetchone()
    if not item:
        flash('Yêu cầu này đã được xử lý hoặc không tồn tại.', 'error')
    else:
        db.execute("UPDATE urgent_purchase_requests SET status='completed',handled_by=?,handled_at=? WHERE id=?",
                   (session['user_id'], datetime.now().isoformat(timespec='seconds'), request_id))
        db.commit()
        flash('Đã đánh dấu yêu cầu nhập gấp là đã xử lý.', 'success')
    return redirect(url_for('accounting.index'))
