import click
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash
from models.repository import INTEGRITY_ERRORS, record_audit
from models.workflows import atomic


@click.command('create-admin')
@click.option('--name',required=True)
@click.option('--email',required=True)
@click.password_option()
@with_appcontext
def create_admin(name,email,password):
    """Provision an administrator explicitly; remote databases never seed demo users."""
    name,email=name.strip(),email.strip().lower()
    if not name or '@' not in email or len(password)<12:
        raise click.ClickException('Tên/email không hợp lệ hoặc mật khẩu ngắn hơn 12 ký tự.')
    try:
        with atomic() as db:
            db.execute('INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)',
                       (name,email,generate_password_hash(password,method='pbkdf2:sha256'),'admin'))
            uid=db.execute('SELECT last_insert_rowid()').fetchone()[0]
            record_audit(uid,'admin_created_cli','user',uid)
    except INTEGRITY_ERRORS:
        raise click.ClickException('Email đã tồn tại. Không ghi đè tài khoản hoặc mật khẩu hiện có.')
    click.echo('Đã tạo tài khoản Admin.')


def register_commands(app):
    app.cli.add_command(create_admin)
