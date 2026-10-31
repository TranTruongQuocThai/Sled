import click
import os
from pathlib import Path
from flask import Flask
from werkzeug.security import generate_password_hash
from controllers.auth import auth_bp
from controllers.dashboard import dashboard_bp
from controllers.inventory import inventory_bp
from controllers.orders import orders_bp
from controllers.accounting import accounting_bp
from models.repository import init_db


def create_app(test_config=None):
    app = Flask(__name__)
    on_vercel = bool(os.environ.get("VERCEL"))
    secret_key = os.environ.get("SECRET_KEY", "")
    turso_url = os.environ.get("TURSO_DATABASE_URL", "")
    turso_token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if on_vercel and not secret_key:
        raise RuntimeError("SECRET_KEY is required on Vercel.")
    if on_vercel and not (turso_url and turso_token):
        raise RuntimeError("TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are required on Vercel.")
    project_dir = Path(__file__).resolve().parent
    app.config.from_mapping(
        SECRET_KEY=secret_key or "sled-local-development-only",
        DATABASE=os.environ.get("SLED_DATABASE", str(project_dir / "warehouse.db")),
        SEED_DEMO=not (on_vercel or bool(turso_url)),
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        TURSO_DATABASE_URL=turso_url,
        TURSO_AUTH_TOKEN=turso_token,
        SESSION_COOKIE_SECURE=on_vercel,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)
    from models.security import install_security
    install_security(app)
    @app.errorhandler(OverflowError)
    def invalid_numeric_value(error):
        return 'Giá trị số vượt giới hạn cho phép.', 400

    from models.commands import register_commands
    register_commands(app)
    init_db(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(accounting_bp)
    return app


app = create_app()


@app.cli.command("reset-demo-passwords")
def reset_demo_passwords():
    """Reset the local development accounts to the documented ASCII passwords."""
    from models.repository import get_db
    passwords = {
        "manager@khoflow.local": "Manager123!",
        "sale@khoflow.local": "Sale123!",
        "tho@khoflow.local": "Tho123!",
        "ketoan@khoflow.local": "KeToan123!",
    }
    db = get_db()
    for email, password in passwords.items():
        db.execute("UPDATE users SET password_hash=? WHERE email=?",
                   (generate_password_hash(password, method="pbkdf2:sha256"), email))
    db.commit()
    click.echo("Đã đặt lại mật khẩu cho các tài khoản mẫu.")

if __name__ == "__main__":
    # Keep one stable local process; the debug reloader can exit when launched
    # from an IDE task or a detached terminal.
    app.run(debug=True, use_reloader=False, host="127.0.0.1", port=5000)
