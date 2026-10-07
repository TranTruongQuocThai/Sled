import sqlite3
from datetime import datetime
from flask import current_app, g
from werkzeug.security import generate_password_hash


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        db = get_db()
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','sales','technician','accountant'))
        );
        CREATE TABLE IF NOT EXISTS components (
          id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
          unit TEXT NOT NULL DEFAULT 'cái', stock INTEGER NOT NULL DEFAULT 0,
          reserved INTEGER NOT NULL DEFAULT 0, min_stock INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS component_categories (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS commission_rules (
          threshold INTEGER PRIMARY KEY, rate REAL NOT NULL CHECK(rate >= 0 AND rate <= 100)
        );
        CREATE TABLE IF NOT EXISTS products (
          id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, price INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS product_components (
          product_id INTEGER NOT NULL, component_id INTEGER NOT NULL, quantity INTEGER NOT NULL,
          PRIMARY KEY(product_id, component_id), FOREIGN KEY(product_id) REFERENCES products(id),
          FOREIGN KEY(component_id) REFERENCES components(id)
        );
        CREATE TABLE IF NOT EXISTS orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, customer_name TEXT NOT NULL,
          customer_phone TEXT, delivery_address TEXT, note TEXT, product_id INTEGER NOT NULL,
          quantity INTEGER NOT NULL, total INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
          progress INTEGER NOT NULL DEFAULT 0, created_by INTEGER NOT NULL, created_at TEXT NOT NULL,
          accepted_by INTEGER, accepted_at TEXT,
          FOREIGN KEY(product_id) REFERENCES products(id), FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS inventory_transactions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, component_id INTEGER NOT NULL,
          quantity INTEGER NOT NULL, transaction_type TEXT NOT NULL CHECK(transaction_type IN ('in','adjustment')),
          note TEXT, created_by INTEGER NOT NULL, created_at TEXT NOT NULL,
          FOREIGN KEY(component_id) REFERENCES components(id), FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS urgent_purchase_requests (
          id INTEGER PRIMARY KEY AUTOINCREMENT, component_id INTEGER NOT NULL,
          requested_quantity INTEGER NOT NULL, note TEXT, status TEXT NOT NULL DEFAULT 'open',
          created_by INTEGER NOT NULL, created_at TEXT NOT NULL,
          handled_by INTEGER, handled_at TEXT,
          FOREIGN KEY(component_id) REFERENCES components(id), FOREIGN KEY(created_by) REFERENCES users(id),
          FOREIGN KEY(handled_by) REFERENCES users(id)
        );
        """)
        users_schema = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()['sql']
        if "'accountant'" not in users_schema:
            db.executescript("""
            CREATE TABLE users_admin_migration (
              id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
              password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','sales','technician','accountant'))
            );
            INSERT INTO users_admin_migration(id,name,email,password_hash,role)
              SELECT id,name,email,password_hash,CASE WHEN role='manager' THEN 'admin' ELSE role END FROM users;
            DROP TABLE users;
            ALTER TABLE users_admin_migration RENAME TO users;
            """)
        # Migration for databases created before the assignment workflow was added.
        order_columns = {row["name"] for row in db.execute("PRAGMA table_info(orders)")}
        if "accepted_by" not in order_columns:
            db.execute("ALTER TABLE orders ADD COLUMN accepted_by INTEGER")
        if "accepted_at" not in order_columns:
            db.execute("ALTER TABLE orders ADD COLUMN accepted_at TEXT")
        if "progress" not in order_columns:
            db.execute("ALTER TABLE orders ADD COLUMN progress INTEGER NOT NULL DEFAULT 0")
        component_columns = {row["name"] for row in db.execute("PRAGMA table_info(components)")}
        if "category_id" not in component_columns:
            db.execute("ALTER TABLE components ADD COLUMN category_id INTEGER")
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            seed(db)
        else:
            db.execute("""INSERT OR IGNORE INTO users(name,email,password_hash,role) VALUES(?,?,?,?)""",
                       ('Phạm Thu Hà', 'ketoan@khoflow.local', generate_password_hash('KeToan123!', method='pbkdf2:sha256'), 'accountant'))
        seed_component_categories(db)
        seed_commission_rules(db)
        db.commit()


def seed(db):
    staff = [("Trần Quốc Huy", "manager@khoflow.local", "admin", "Manager123!"),
             ("Nguyễn Minh Anh", "sale@khoflow.local", "sales", "Sale"),
             ("Lê Gia Bảo", "tho@khoflow.local", "technician", "Thợ"),
             ("Phạm Thu Hà", "ketoan@khoflow.local", "accountant", "KeToan123!")]
    for name, email, role, password in staff:
        db.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)",
                   (name, email, generate_password_hash(password, method='pbkdf2:sha256'), role))
    parts = [("LK-001", "Khung nhôm 6061", "cái", 42, 8, 15), ("LK-002", "Bánh xe 80mm", "cái", 116, 24, 40),
             ("LK-003", "Motor DC 24V", "cái", 18, 6, 20), ("LK-004", "Bộ điều khiển M1", "bộ", 27, 3, 10),
             ("LK-005", "Pin lithium 24V", "bộ", 11, 2, 12)]
    db.executemany("INSERT INTO components(sku,name,unit,stock,reserved,min_stock) VALUES(?,?,?,?,?,?)", parts)
    db.execute("INSERT INTO products(sku,name,price) VALUES('SP-001','Xe đẩy tự hành S1',18000000)")
    ids = {row['sku']: row['id'] for row in db.execute("SELECT id,sku FROM components")}
    product_id = db.execute("SELECT id FROM products WHERE sku='SP-001'").fetchone()['id']
    db.executemany("INSERT INTO product_components(product_id,component_id,quantity) VALUES(?,?,?)",
                   [(product_id, ids['LK-001'], 1), (product_id, ids['LK-002'], 4), (product_id, ids['LK-003'], 2), (product_id, ids['LK-004'], 1), (product_id, ids['LK-005'], 1)])
    admin = db.execute("SELECT id FROM users WHERE role='admin'").fetchone()['id']
    sale = db.execute("SELECT id FROM users WHERE role='sales'").fetchone()['id']
    now = datetime.now().isoformat(timespec='seconds')
    db.executemany("INSERT INTO orders(code,customer_name,customer_phone,delivery_address,note,product_id,quantity,total,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", [
      ('DH-24091','Công ty An Phát','0901000001','Quận 7, TP.HCM','',product_id,3,54000000,'pending',sale,now),
      ('DH-24087','Kho vận Đại Nam','0901000002','Bình Dương','',product_id,2,36000000,'confirmed',sale,now),
      ('DH-24084','Cơ khí Hoàng Long','0901000003','Đồng Nai','',product_id,5,90000000,'producing',admin,now)])


def seed_component_categories(db):
    defaults = ('Khung & cơ khí', 'Điện & điều khiển', 'Pin & năng lượng', 'Bánh xe & truyền động')
    db.executemany("INSERT OR IGNORE INTO component_categories(name) VALUES(?)", [(name,) for name in defaults])
    category_ids = {row['name']: row['id'] for row in db.execute("SELECT id,name FROM component_categories")}
    category_by_sku = {
        'LK-001': 'Khung & cơ khí', 'LK-002': 'Bánh xe & truyền động',
        'LK-003': 'Điện & điều khiển', 'LK-004': 'Điện & điều khiển', 'LK-005': 'Pin & năng lượng',
    }
    for sku, category in category_by_sku.items():
        db.execute("UPDATE components SET category_id=? WHERE sku=? AND category_id IS NULL",
                   (category_ids[category], sku))


def seed_commission_rules(db):
    rules = ((0, 1), (200_000_000, 3), (500_000_000, 5))
    db.executemany("INSERT OR IGNORE INTO commission_rules(threshold,rate) VALUES(?,?)", rules)


def query_orders(user):
    sql = """SELECT o.*, p.name product_name, u.name owner_name, receiver.name receiver_name FROM orders o
             JOIN products p ON p.id=o.product_id JOIN users u ON u.id=o.created_by
             LEFT JOIN users receiver ON receiver.id=o.accepted_by"""
    args = []
    if user['role'] == 'sales':
        sql += " WHERE o.created_by=?"; args.append(user['id'])
    return get_db().execute(sql + " ORDER BY o.id DESC", args).fetchall()


def product_requirements(product_id, order_quantity):
    return get_db().execute("""SELECT c.*, pc.quantity AS per_product,
      pc.quantity * ? AS required, (c.stock-c.reserved) AS available,
      (c.stock-c.reserved-(pc.quantity * ?)) AS remaining
      FROM product_components pc JOIN components c ON c.id=pc.component_id WHERE pc.product_id=?""",
      (order_quantity, order_quantity, product_id)).fetchall()


def product_capacity():
    """Return the maximum buildable quantity for every product based on available components."""
    return get_db().execute("""SELECT p.id, p.sku, p.name, p.price,
      COALESCE(MIN(CAST((c.stock - c.reserved) / pc.quantity AS INTEGER)), 0) AS buildable,
      GROUP_CONCAT(CASE WHEN (c.stock - c.reserved) < pc.quantity THEN c.name END) AS shortages
      FROM products p LEFT JOIN product_components pc ON pc.product_id=p.id
      LEFT JOIN components c ON c.id=pc.component_id
      GROUP BY p.id ORDER BY p.name""").fetchall()
