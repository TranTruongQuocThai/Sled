"""Review a read-only backup; never migrate the real warehouse database."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
source=root/'warehouse.db'
with tempfile.TemporaryDirectory() as temporary:
    target=Path(temporary)/'review.db'
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as original:
        with closing(sqlite3.connect(target)) as backup:
            original.backup(backup)
    with closing(sqlite3.connect(target)) as db:
        before_orders=db.execute('SELECT id,code,status,created_by,total FROM orders ORDER BY id').fetchall()
        before_snapshots=db.execute('SELECT * FROM order_component_requirements ORDER BY order_id,component_id').fetchall()
    os.environ.update(SLED_DATABASE=str(target),TURSO_DATABASE_URL='',TURSO_AUTH_TOKEN='',VERCEL='')
    from app import app,create_app
    from models.repository import get_db
    create_app({'DATABASE':str(target),'TURSO_DATABASE_URL':'','TURSO_AUTH_TOKEN':''})
    with app.app_context():
        db=get_db()
        assert [tuple(r) for r in db.execute('SELECT id,code,status,created_by,total FROM orders ORDER BY id')]==before_orders
        assert [tuple(r) for r in db.execute('SELECT * FROM order_component_requirements ORDER BY order_id,component_id')]==before_snapshots
        output={
            'migration_repeated_preserves_orders_and_snapshots':True,
            'foreign_key_issues':len(db.execute('PRAGMA foreign_key_check').fetchall()),
            'orders':len(before_orders),
            'legacy_status_orders':db.execute("SELECT COUNT(*) FROM orders WHERE status IN ('confirmed','producing')").fetchone()[0],
            'items_without_provable_bom_version':db.execute('SELECT COUNT(*) FROM sales_order_items WHERE bom_id IS NULL').fetchone()[0],
            'invalid_stock_rows':db.execute('SELECT COUNT(*) FROM components WHERE stock<reserved+blocked OR reserved<0 OR blocked<0').fetchone()[0],
            'reservation_balance_mismatches':db.execute('''SELECT COUNT(*) FROM components c WHERE ABS(c.reserved-COALESCE((
                SELECT SUM(CASE WHEN t.transaction_type='reserve' THEN t.quantity ELSE -t.quantity END)
                FROM stock_reservation_transactions t JOIN orders o ON o.id=t.order_id
                WHERE t.component_id=c.id AND o.material_status='reserved'),0))>0.0000001''').fetchone()[0]
        }
        print(json.dumps(output,indent=2))
