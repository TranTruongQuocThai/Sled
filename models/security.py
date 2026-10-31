from hmac import compare_digest
from secrets import token_urlsafe
from flask import abort, request, session
from markupsafe import Markup


def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = token_urlsafe(32)
    return session['_csrf']


def install_security(app):
    app.jinja_env.globals['csrf_token'] = csrf_token
    app.jinja_env.globals['csrf_field'] = lambda: Markup('<input type="hidden" name="csrf_token" value="{}">').format(csrf_token())

    @app.before_request
    def protect_mutations():
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
            expected = session.get('_csrf', '')
            if not expected or not compare_digest(expected.encode(), supplied.encode()):
                abort(400, description='Phiên làm việc đã hết hạn. Tải lại trang rồi thử lại.')
