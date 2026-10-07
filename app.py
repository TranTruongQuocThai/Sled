import click
from flask import Flask
from werkzeug.security import generate_password_hash
from controllers.auth import auth_bp
from controllers.dashboard import dashboard_bp
from controllers.inventory import inventory_bp
from controllers.orders import orders_bp
from controllers.accounting import accounting_bp
from models.repository import init_db


def create_app():
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY="change-this-secret-before-production",
        DATABASE="warehouse.db",
    )
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
