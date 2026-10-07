from functools import wraps
import sqlite3
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from models.repository import get_db

auth_bp = Blueprint('auth', __name__)

def login_required(roles=None):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('auth.login'))
            if roles and session.get('role') not in roles:
                flash('Bạn không có quyền truy cập chức năng này.', 'error')
                return redirect(url_for('dashboard.home'))
            return view(*args, **kwargs)
        return wrapped
    return decorator

@auth_bp.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        user = get_db().execute('SELECT * FROM users WHERE email=?', (request.form['email'].strip().lower(),)).fetchone()
        if user and check_password_hash(user['password_hash'], request.form['password']):
            session.clear(); session.update(user_id=user['id'], user_name=user['name'], role=user['role'])
            return redirect(url_for('dashboard.home'))
        flash('Email hoặc mật khẩu không đúng.', 'error')
    return render_template('login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if session.get('user_id'):
        return redirect(url_for('dashboard.home'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        role = request.form.get('role', 'sales')
        if not name or not email or not password:
            flash('Vui lòng nhập đầy đủ họ tên, email và mật khẩu.', 'error')
        elif role not in ('sales', 'technician', 'accountant'):
            flash('Vai trò đăng ký không hợp lệ.', 'error')
        elif len(password) < 6:
            flash('Mật khẩu cần có ít nhất 6 ký tự.', 'error')
        elif password != confirm_password:
            flash('Xác nhận mật khẩu không khớp.', 'error')
        else:
            try:
                db = get_db()
                db.execute('INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)',
                           (name, email, generate_password_hash(password, method='pbkdf2:sha256'), role))
                db.commit()
                flash('Đăng ký thành công. Hãy đăng nhập để tiếp tục.', 'success')
                return redirect(url_for('auth.login'))
            except sqlite3.IntegrityError:
                flash('Email này đã được đăng ký.', 'error')
    return render_template('register.html')

@auth_bp.route('/logout')
def logout():
    session.clear(); return redirect(url_for('auth.login'))
