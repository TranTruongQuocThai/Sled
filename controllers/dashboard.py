from datetime import datetime
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from controllers.auth import login_required
from models.repository import record_audit, get_db, product_capacity, query_orders

dashboard_bp = Blueprint('dashboard', __name__)


def sales_monthly_report(user_id):
    rows = get_db().execute("""SELECT substr(created_at, 1, 7) AS month,
                              COUNT(*) AS order_count, COALESCE(SUM(total), 0) AS total
                              FROM orders WHERE created_by=? AND status!='cancelled' GROUP BY substr(created_at, 1, 7)""",
                            (user_id,)).fetchall()
    totals = {row['month']: {'total': row['total'], 'order_count': row['order_count']} for row in rows}
    now = datetime.now()
    months = []
    for offset in range(11, -1, -1):
        year = now.year
        month = now.month - offset
        while month <= 0:
            month += 12
            year -= 1
        key = f'{year:04d}-{month:02d}'
        data = totals.get(key, {'total': 0, 'order_count': 0})
        months.append({'key': key, 'label': f'T{month}', **data})
    maximum = max((item['total'] for item in months), default=0)
    for item in months:
        item['height'] = max(8, round(item['total'] * 100 / maximum)) if maximum else 8
    return months
@dashboard_bp.route('/')
@login_required()
def home():
    db=get_db(); user={'id':session['user_id'],'role':session['role']}
    orders=query_orders(user)
    workflow_stats={key:sum(1 for o in orders if o['status']=='pending' and (key=='waiting' or o['material_status']==key))
                    for key in ('waiting','pending_material','pending_approval','unknown')}
    if session['role'] == 'sales':
        total_value = sum(order['total'] for order in orders if order['status']!='cancelled')
        sales_stats = {
            'order_count': len(orders),
            'waiting_count': sum(order['status'] in ('pending', 'confirmed') for order in orders),
            'total_value': total_value,
        }
        return render_template('dashboard.html', workflow_stats=workflow_stats, components=[], low=[], orders=orders[:4], total_components=0,
                               sales_stats=sales_stats, product_capacity=product_capacity())
    if session['role'] == 'accountant':
        components = db.execute('SELECT * FROM components ORDER BY name').fetchall()
        low = [item for item in components if item['stock'] - item['reserved'] - item['blocked'] <= item['min_stock']]
        return render_template('dashboard.html', workflow_stats=workflow_stats, components=components, low=low, orders=orders[:4], total_components=sum(x['stock'] for x in components))
    if session['role'] == 'admin':
        admin_stats = db.execute("""SELECT COUNT(*) AS order_count, COALESCE(SUM(CASE WHEN status!='cancelled' THEN total ELSE 0 END), 0) AS revenue
                                    FROM orders""").fetchone()
        team_counts = {row['role']: row['count'] for row in db.execute(
            "SELECT role, COUNT(*) AS count FROM users GROUP BY role")}
        technician_revenue = db.execute("""SELECT COALESCE(SUM(o.total), 0) AS revenue
                                           FROM orders o JOIN users u ON u.id=o.production_by
                                           WHERE u.role='technician' AND o.status!='cancelled'""").fetchone()['revenue']
        commission_rules = db.execute('SELECT threshold,rate FROM commission_rules ORDER BY threshold').fetchall()
        return render_template('dashboard.html', workflow_stats=workflow_stats, components=[], low=[], orders=orders[:5], total_components=0,
                               admin_stats=admin_stats, team_counts=team_counts,
                               technician_revenue=technician_revenue, commission_rules=commission_rules)
    components=db.execute('SELECT * FROM components ORDER BY name').fetchall()
    low=[item for item in components if item['stock']-item['reserved']-item['blocked'] <= item['min_stock']]
    return render_template('dashboard.html', workflow_stats=workflow_stats, components=components, low=low, orders=orders[:4], total_components=sum(x['stock'] for x in components),
                           product_capacity=product_capacity())


@dashboard_bp.route('/reports')
@login_required(['sales'])
def reports():
    db = get_db()
    user_id = session['user_id']
    summary = db.execute("""SELECT COUNT(*) AS order_count, COALESCE(SUM(total), 0) AS total_value,
                            COALESCE(AVG(total), 0) AS average_value
                            FROM orders WHERE created_by=? AND status!='cancelled'""", (user_id,)).fetchone()
    months = sales_monthly_report(user_id)
    top_month = max(months, key=lambda item: item['total']) if months else None
    return render_template('sales_reports.html', summary=summary, months=months, top_month=top_month)


@dashboard_bp.route('/team')
@login_required(['admin'])
def team():
    db = get_db()
    sales = db.execute("""SELECT u.*, COUNT(o.id) AS order_count, COALESCE(SUM(o.total), 0) AS revenue
                          FROM users u LEFT JOIN orders o ON o.created_by=u.id AND o.status!='cancelled'
                          WHERE u.role='sales' GROUP BY u.id ORDER BY u.name""").fetchall()
    technicians = db.execute("""SELECT u.*, COUNT(o.id) AS handled_count, COALESCE(SUM(o.total), 0) AS revenue
                                FROM users u LEFT JOIN orders o ON o.production_by=u.id AND o.status!='cancelled'
                                WHERE u.role='technician' GROUP BY u.id ORDER BY u.name""").fetchall()
    accountants = db.execute("""SELECT u.*, COUNT(t.id) AS entry_count FROM users u
                               LEFT JOIN stock_movements t ON t.created_by=u.id
                               WHERE u.role='accountant' GROUP BY u.id ORDER BY u.name""").fetchall()
    users = db.execute("SELECT id,name,email,role FROM users ORDER BY CASE role WHEN 'admin' THEN 0 WHEN 'sales' THEN 1 WHEN 'technician' THEN 2 ELSE 3 END, name").fetchall()
    return render_template('admin_team.html', sales=sales, technicians=technicians, accountants=accountants, users=users)


@dashboard_bp.route('/team/<int:user_id>/role', methods=['POST'])
@login_required(['admin'])
def update_role(user_id):
    if user_id == session['user_id']:
        flash('Admin không thể tự thay đổi vai trò của chính mình.', 'error')
        return redirect(url_for('dashboard.team'))
    role = request.form.get('role')
    if role not in ('admin', 'sales', 'technician', 'accountant', 'warehouse', 'purchasing'):
        abort(400)
    result = get_db().execute('UPDATE users SET role=? WHERE id=?', (role, user_id))
    if result.rowcount:
        record_audit(session['user_id'],'role_changed','user',user_id,role)
    get_db().commit()
    flash('Đã cập nhật vai trò tài khoản.' if result.rowcount else 'Không tìm thấy tài khoản.', 'success' if result.rowcount else 'error')
    return redirect(url_for('dashboard.team'))


@dashboard_bp.route('/commission-rules/save', methods=['POST'])
@login_required(['admin'])
def save_commission_rule():
    try:
        original_threshold = request.form.get('original_threshold')
        threshold = int(request.form.get('threshold', ''))
        rate = float(request.form.get('rate', ''))
        if threshold < 0 or not 0 <= rate <= 100:
            raise ValueError
        db = get_db()
        if original_threshold is not None and int(original_threshold) != threshold:
            if int(original_threshold) == 0:
                flash('Không thể thay đổi mốc bắt đầu 0đ.', 'error')
                return redirect(url_for('dashboard.home'))
            db.execute('DELETE FROM commission_rules WHERE threshold=?', (int(original_threshold),))
        db.execute("INSERT INTO commission_rules(threshold,rate) VALUES(?,?) ON CONFLICT(threshold) DO UPDATE SET rate=excluded.rate",
                   (threshold, rate))
        db.commit()
        flash('Đã lưu quy tắc hoa hồng.', 'success')
    except (TypeError, ValueError):
        flash('Mốc doanh thu hoặc phần trăm hoa hồng chưa hợp lệ.', 'error')
    return redirect(url_for('dashboard.home'))


@dashboard_bp.route('/commission-rules/<int:threshold>/delete', methods=['POST'])
@login_required(['admin'])
def delete_commission_rule(threshold):
    if threshold == 0:
        flash('Không thể xóa mốc hoa hồng bắt đầu 0đ.', 'error')
    else:
        get_db().execute('DELETE FROM commission_rules WHERE threshold=?', (threshold,))
        get_db().commit()
        flash('Đã xóa mốc hoa hồng.', 'success')
    return redirect(url_for('dashboard.home'))
