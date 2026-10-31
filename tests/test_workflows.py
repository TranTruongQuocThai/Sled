from contextlib import closing
import atexit
import io
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from openpyxl import Workbook
from werkzeug.datastructures import FileStorage, MultiDict

# Importing app must never initialize or mutate the operator's warehouse.db.
_bootstrap = tempfile.TemporaryDirectory()
atexit.register(_bootstrap.cleanup)
with patch.dict(os.environ, {'SLED_DATABASE': str(Path(_bootstrap.name)/'bootstrap.db'),
                              'TURSO_DATABASE_URL':'','TURSO_AUTH_TOKEN':'','VERCEL':''}):
    from app import create_app
from models.repository import get_db, init_db, product_capacity
from models.workflows import (activate_bom, advance_order, cancel_order, check_items,
    create_order, quantity, receive_purchase, request_purchase, reserve_order, save_draft)
from models.excel_imports import commit_import, preview_import


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_dir=tempfile.TemporaryDirectory()
        cls.fixture=str(Path(cls.fixture_dir.name)/'fixture.db')
        app=create_app(cls.config(cls.fixture))
        with app.app_context():
            db=get_db()
            db.execute('DELETE FROM sales_order_items')
            db.execute('DELETE FROM order_component_requirements')
            db.execute('DELETE FROM orders')
            db.execute('UPDATE components SET stock=100,reserved=0,blocked=0')
            for role in ('warehouse','purchasing'):
                db.execute('INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)',(role,role+'@test.local','unused',role))
            db.execute("INSERT INTO products(sku,name,price) VALUES('SP-002','Second product',1000)")
            db.commit()
            bom=save_draft(2,[(1,2),(3,1)],1)
            activate_bom(bom,1)

    @classmethod
    def tearDownClass(cls):
        cls.fixture_dir.cleanup()

    @staticmethod
    def config(database):
        return dict(TESTING=True,SECRET_KEY='test-only',DATABASE=database,TURSO_DATABASE_URL='',TURSO_AUTH_TOKEN='')

    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.database=str(Path(self.directory.name)/'test.db')
        shutil.copyfile(self.fixture,self.database)
        self.app=create_app(self.config(self.database))
        self.client=self.app.test_client()
        with self.app.app_context():
            self.users={r['role']:r['id'] for r in get_db().execute('SELECT id,role FROM users')}

    def tearDown(self):
        self.directory.cleanup()

    def login_as(self,role,client=None):
        with (client or self.client).session_transaction() as session:
            session.update(user_id=self.users[role],user_name=role,role=role)

    def post(self,path,data=None,client=None,**kwargs):
        client=client or self.client
        with client.session_transaction() as session:
            session.setdefault('_csrf','test-token')
            token=session['_csrf']
        return client.post(path,data=data or {},headers={'X-CSRF-Token':token},**kwargs)

    def call(self,func,*args,**kwargs):
        with self.app.app_context():
            return func(*args,**kwargs)

    def sql(self,sql,args=()):
        with self.app.app_context():
            db=get_db()
            rows=db.execute(sql,args).fetchall()
            db.commit()
            return [dict(r) for r in rows]

    def order(self,items=None):
        return self.call(create_order,items or [(1,1)],{'customer_name':'Test customer'},self.users['sales'])

    def excel(self,rows):
        book=Workbook()
        for row in rows:
            book.active.append(row)
        data=io.BytesIO()
        book.save(data)
        book.close()
        data.seek(0)
        return FileStorage(stream=data,filename='test.xlsx')

    def preview(self,rows,kind='components'):
        return self.call(preview_import,self.excel(rows),kind,self.users['admin'])

    def concurrent(self,actions):
        barrier=threading.Barrier(len(actions))
        def worker(action):
            barrier.wait(timeout=5)
            try:
                self.call(action)
                return 'ok'
            except ValueError:
                return 'rejected'
        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            return list(pool.map(worker,actions))

    def test_multi_product_requirements_aggregate_shared_components(self):
        result=self.call(check_items,[(1,3),(2,4)])
        parts={r['component_id']:r for r in result['requirements']}
        self.assertEqual(parts[1]['required'],11)
        self.assertEqual(parts[3]['required'],10)
        oid=self.order([(1,3),(2,4)])
        self.assertEqual(len(self.sql('SELECT * FROM sales_order_items WHERE order_id=?',(oid,))),2)
        self.assertEqual(self.sql('SELECT total FROM orders WHERE id=?',(oid,))[0]['total'],54004000)

    def test_missing_bom_is_unknown_and_cannot_reserve_even_after_later_bom(self):
        self.sql("INSERT INTO products(sku,name,price) VALUES('NO-BOM','No BOM',0)")
        oid=self.order([(1,1),(3,1)])
        self.assertEqual(self.sql('SELECT material_status FROM orders WHERE id=?',(oid,))[0]['material_status'],'unknown')
        bom=self.call(save_draft,3,[(1,1)],1)
        self.call(activate_bom,bom,1)
        with self.assertRaises(ValueError):
            self.call(reserve_order,oid,self.users['warehouse'])

    def test_invalid_quantities_rejected(self):
        for value in ('0','-1','NaN','Infinity','0.0000001','1000000001','oops'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                quantity(value)
        with self.assertRaises(ValueError):
            self.call(check_items,[(1,'1.5')])
        with self.assertRaises(ValueError):
            self.call(check_items,[])

    def test_blocked_stock_is_excluded_in_all_checks(self):
        self.sql('UPDATE components SET blocked=100 WHERE id=1')
        result=self.call(check_items,[(1,1)])
        self.assertEqual(result['material_status'],'pending_material')
        self.assertEqual(result['requirements'][0]['available'],0)
        self.assertEqual(self.call(product_capacity)[0]['buildable'],0)
        self.login_as('sales')
        self.assertEqual(self.client.get('/inventory/forecast?product_id=1&quantity=1').get_json()[0]['available'],0)
        oid=self.order()
        with self.assertRaises(ValueError):
            self.call(reserve_order,oid,self.users['warehouse'])

    def test_create_reserve_cancel_does_not_change_physical_stock(self):
        oid=self.order()
        self.assertEqual(self.sql('SELECT reserved FROM components WHERE id=1')[0]['reserved'],0)
        self.call(reserve_order,oid,self.users['warehouse'])
        self.assertEqual(self.sql('SELECT reserved FROM components WHERE id=1')[0]['reserved'],1)
        self.call(cancel_order,oid,self.users['sales'],'sales')
        self.assertEqual(self.sql('SELECT stock,reserved FROM components WHERE id=1')[0],dict(stock=100,reserved=0))
        self.assertEqual([r['movement_type'] for r in self.sql('SELECT movement_type FROM stock_movements WHERE order_id=?',(oid,))],['reserve']*5+['release']*5)

    def test_reservation_rolls_back_all_components_on_last_shortage(self):
        self.sql('UPDATE components SET stock=0 WHERE id=5')
        oid=self.order()
        with self.assertRaises(ValueError):
            self.call(reserve_order,oid,self.users['warehouse'])
        self.assertEqual(sum(r['reserved'] for r in self.sql('SELECT reserved FROM components')),0)
        self.assertEqual(len(self.sql('SELECT * FROM stock_reservation_transactions')),0)
        self.assertEqual(self.sql('SELECT status FROM orders WHERE id=?',(oid,))[0]['status'],'pending')

    def test_two_orders_cannot_over_reserve_concurrently(self):
        a,b=self.order([(2,40)]),self.order([(2,40)])
        results=self.concurrent([lambda: reserve_order(a,self.users['warehouse']),lambda: reserve_order(b,self.users['warehouse'])])
        self.assertCountEqual(results,['ok','rejected'])
        self.assertEqual(self.sql('SELECT reserved FROM components WHERE id=1')[0]['reserved'],80)

    def test_same_order_cannot_be_reserved_twice_concurrently(self):
        oid=self.order()
        results=self.concurrent([lambda: reserve_order(oid,self.users['warehouse'])]*2)
        self.assertCountEqual(results,['ok','rejected'])
        self.assertEqual(self.sql('SELECT reserved FROM components WHERE id=1')[0]['reserved'],1)
        self.assertEqual(len(self.sql('SELECT * FROM stock_reservation_transactions WHERE order_id=?',(oid,))),5)

    def test_double_cancellation_does_not_release_other_orders(self):
        a,b=self.order(),self.order()
        self.call(reserve_order,a,self.users['warehouse'])
        self.call(reserve_order,b,self.users['warehouse'])
        results=self.concurrent([lambda: cancel_order(a,self.users['admin'],'admin')]*2)
        self.assertCountEqual(results,['ok','rejected'])
        self.assertEqual(self.sql('SELECT reserved FROM components WHERE id=1')[0]['reserved'],1)
        with self.assertRaises(ValueError):
            self.call(reserve_order,a,self.users['warehouse'])

    def test_stock_is_issued_at_start_of_production_once(self):
        oid=self.order()
        self.call(reserve_order,oid,self.users['warehouse'])
        with self.assertRaises(ValueError):
            self.call(advance_order,oid,'installing',self.users['technician'],'technician')
        self.call(advance_order,oid,'installing',self.users['warehouse'],'warehouse')
        self.assertEqual(self.sql('SELECT stock,reserved FROM components WHERE id=1')[0],dict(stock=99,reserved=0))
        with self.assertRaises(ValueError):
            self.call(cancel_order,oid,self.users['admin'],'admin')
        for stage in ('testing','completed','delivering'):
            self.call(advance_order,oid,stage,self.users['technician'],'technician')
        self.assertEqual(self.sql('SELECT stock FROM components WHERE id=1')[0]['stock'],99)
        self.assertEqual(len(self.sql('SELECT * FROM stock_issues WHERE order_id=?',(oid,))),5)

    def test_concurrent_production_start_issues_once(self):
        oid=self.order()
        self.call(reserve_order,oid,self.users['warehouse'])
        results=self.concurrent([lambda: advance_order(oid,'installing',self.users['warehouse'],'warehouse')]*2)
        self.assertCountEqual(results,['ok','rejected'])
        self.assertEqual(self.sql('SELECT stock,reserved FROM components WHERE id=1')[0],dict(stock=99,reserved=0))

    def test_cancelled_order_cannot_reenter_production(self):
        oid=self.order()
        self.call(reserve_order,oid,self.users['warehouse'])
        self.call(cancel_order,oid,self.users['admin'],'admin')
        with self.assertRaises(ValueError):
            self.call(advance_order,oid,'accepted',self.users['admin'],'admin')

    def test_draft_bom_does_not_replace_active_bom_until_activation(self):
        original=self.call(check_items,[(1,1)])['requirements']
        bom=self.call(save_draft,1,[(1,3)],self.users['technician'])
        self.assertEqual(self.call(check_items,[(1,1)])['requirements'],original)
        self.call(save_draft,1,[(1,4),(2,2)],self.users['technician'],bom)
        self.call(activate_bom,bom,self.users['technician'])
        self.assertEqual(self.call(check_items,[(1,1)])['requirements'][0]['required'],4)
        with self.assertRaises(ValueError):
            self.call(save_draft,1,[(1,99)],self.users['technician'],bom)
        self.assertEqual(len(self.sql("SELECT * FROM boms WHERE product_id=1 AND status='active'")),1)

    def test_duplicate_or_unknown_bom_components_do_not_save(self):
        before=len(self.sql('SELECT * FROM boms'))
        for items in ([(1,1),(1,2)],[(999,1)],[],[(1,0)]):
            with self.subTest(items=items),self.assertRaises(ValueError):
                self.call(save_draft,1,items,1)
        self.assertEqual(len(self.sql('SELECT * FROM boms')),before)

    def test_bom_activation_preserves_order_snapshot_and_version(self):
        oid=self.order()
        before=self.sql('SELECT * FROM order_component_requirements WHERE order_id=?',(oid,))
        bom_before=self.sql('SELECT bom_id FROM sales_order_items WHERE order_id=?',(oid,))[0]['bom_id']
        bom=self.call(save_draft,1,[(1,99)],1)
        self.call(activate_bom,bom,1)
        self.assertEqual(self.sql('SELECT * FROM order_component_requirements WHERE order_id=?',(oid,)),before)
        self.assertEqual(self.sql('SELECT bom_id FROM sales_order_items WHERE order_id=?',(oid,))[0]['bom_id'],bom_before)
        self.call(reserve_order,oid,self.users['warehouse'])
        self.assertEqual(self.sql('SELECT reserved FROM components WHERE id=1')[0]['reserved'],1)

    def test_fractional_bom_and_inventory_quantities(self):
        bom=self.call(save_draft,1,[(1,'0.25')],1)
        self.call(activate_bom,bom,1)
        oid=self.order([(1,3)])
        self.call(reserve_order,oid,self.users['warehouse'])
        self.assertEqual(self.sql('SELECT reserved FROM components WHERE id=1')[0]['reserved'],0.75)
        self.call(advance_order,oid,'installing',self.users['warehouse'],'warehouse')
        self.assertEqual(self.sql('SELECT stock FROM components WHERE id=1')[0]['stock'],99.25)

    def test_vietnamese_excel_headers_and_real_row_numbers(self):
        batch,rows,errors=self.preview([['Mã linh kiện','Tên linh kiện','Đơn vị tính','Nhóm linh kiện'],[],['NEW','Dây điện','mét','Điện']])
        self.assertEqual(errors,0)
        self.assertEqual(rows[0][0],3)
        self.call(commit_import,batch,'components',self.users['admin'])
        self.assertEqual(self.sql("SELECT unit,stock FROM components WHERE sku='NEW'")[0],dict(unit='mét',stock=0))

    def test_excel_duplicates_and_invalid_quantity_block_entire_commit(self):
        batch,_,errors=self.preview([['product_sku','component_sku','quantity'],['SP-001','LK-001',1],['SP-001','LK-001',2]],'bom')
        self.assertEqual(errors,1)
        with self.assertRaises(ValueError):
            self.call(commit_import,batch,'bom',self.users['admin'])
        batch,_,errors=self.preview([['product_sku','component_sku','quantity'],['SP-001','LK-001','NaN']],'bom')
        self.assertEqual(errors,1)

    def test_excel_import_is_atomic_and_existing_requires_explicit_mode(self):
        batch,_,errors=self.preview([['sku','name','unit','category'],['NEW','New','cái','New category'],['LK-001','Existing','c�i','']])
        # Preserve the fixture's original unit even if the legacy seed is garbled.
        unit=self.sql('SELECT unit FROM components WHERE id=1')[0]['unit']
        batch,_,errors=self.preview([['sku','name','unit','category'],['NEW','New','cái','New category'],['LK-001','Changed',unit,'']])
        self.assertEqual(errors,0)
        with self.assertRaises(ValueError):
            self.call(commit_import,batch,'components',self.users['admin'])
        self.assertEqual(self.sql("SELECT * FROM components WHERE sku='NEW'"),[])
        self.assertEqual(self.sql("SELECT * FROM component_categories WHERE name='New category'"),[])
        self.call(commit_import,batch,'components',self.users['admin'],'upsert')
        self.assertEqual(self.sql('SELECT stock,name FROM components WHERE id=1')[0],dict(stock=100,name='Changed'))
        with self.assertRaises(ValueError):
            self.call(commit_import,batch,'components',self.users['admin'],'upsert')

    def test_bom_excel_creates_complete_draft_without_merging_or_changing_stock(self):
        batch,_,errors=self.preview([['Mã sản phẩm','Mã linh kiện','Định mức'],['SP-001','LK-001',0.5]],'bom')
        self.assertEqual(errors,0)
        self.call(commit_import,batch,'bom',self.users['admin'])
        draft=self.sql("SELECT id FROM boms WHERE product_id=1 AND status='draft'")[0]['id']
        self.assertEqual(len(self.sql('SELECT * FROM bom_items WHERE bom_id=?',(draft,))),1)
        self.assertEqual(len(self.call(check_items,[(1,1)])['requirements']),5)
        self.call(activate_bom,draft,1)
        self.assertEqual(len(self.call(check_items,[(1,1)])['requirements']),1)
        self.assertEqual(self.sql('SELECT stock FROM components WHERE id=1')[0]['stock'],100)

    def test_excel_commit_rechecks_reference_state_and_rolls_back(self):
        batch,_,_=self.preview([['product_sku','component_sku','quantity'],['SP-001','LK-001',2],['SP-002','LK-002',2]],'bom')
        self.sql('UPDATE components SET active=0 WHERE id=2')
        with self.assertRaises(ValueError):
            self.call(commit_import,batch,'bom',self.users['admin'])
        self.assertEqual(self.sql("SELECT * FROM boms WHERE status='draft'"),[])
        self.assertEqual(self.sql('SELECT status FROM import_batches WHERE id=?',(batch,))[0]['status'],'preview')

    def test_malformed_and_empty_excel_are_controlled_errors(self):
        self.login_as('warehouse')
        response=self.post('/inventory/imports/components/preview',{'file':(io.BytesIO(b'not excel'),'bad.xlsx')})
        self.assertEqual(response.status_code,302)
        with self.assertRaises(ValueError):
            self.preview([['sku','name','unit']])
        with self.assertRaises(ValueError):
            self.preview([['sku','SKU','unit'],['A','B','cái']])

    def test_purchase_receipt_is_once_and_rechecks_without_reservation(self):
        self.sql('UPDATE components SET stock=0 WHERE id=1')
        oid=self.order()
        rid=self.call(request_purchase,oid,self.users['purchasing'])
        with self.assertRaises(ValueError):
            self.call(request_purchase,oid,self.users['purchasing'])
        results=self.concurrent([lambda: receive_purchase(rid,self.users['warehouse'])]*2)
        self.assertCountEqual(results,['ok','rejected'])
        self.assertEqual(self.sql('SELECT stock,reserved FROM components WHERE id=1')[0],dict(stock=1,reserved=0))
        self.assertEqual(self.sql('SELECT material_status FROM orders WHERE id=?',(oid,))[0]['material_status'],'pending_approval')
        self.call(reserve_order,oid,self.users['warehouse'])

    def test_stock_entry_and_adjustment_log_and_refresh(self):
        self.sql('UPDATE components SET stock=0 WHERE id=1')
        oid=self.order()
        self.login_as('warehouse')
        self.assertEqual(self.post('/accounting/stock-entry',{'component_id':1,'quantity':10,'note':'receipt'}).status_code,302)
        self.assertEqual(self.sql('SELECT material_status FROM orders WHERE id=?',(oid,))[0]['material_status'],'pending_approval')
        self.post('/inventory/components/1/stock',{'stock':9,'blocked':2,'note':'count'})
        self.assertEqual(self.sql('SELECT stock,blocked FROM components WHERE id=1')[0],dict(stock=9,blocked=2))
        self.assertEqual(self.sql("SELECT quantity FROM stock_movements WHERE movement_type='adjustment'")[0]['quantity'],-1)
        self.assertEqual(len(self.sql("SELECT * FROM audit_logs WHERE action='blocked_changed'")),1)

    def test_inventory_adjustment_cannot_consume_reserved_stock(self):
        oid=self.order()
        self.call(reserve_order,oid,self.users['warehouse'])
        self.login_as('warehouse')
        self.post('/inventory/components/1/stock',{'stock':1,'blocked':1,'note':'invalid'})
        self.assertEqual(self.sql('SELECT stock,blocked FROM components WHERE id=1')[0],dict(stock=100,blocked=0))

    def test_permissions_separate_warehouse_purchasing_technician_and_accountant(self):
        denied={
            'technician':['/orders/1/accept','/accounting/stock-entry','/orders/1/purchase-request','/inventory/components'],
            'warehouse':['/orders/1/purchase-request','/inventory/bom','/inventory/products'],
            'purchasing':['/orders/1/accept','/accounting/stock-entry','/inventory/bom','/inventory/components'],
            'sales':['/inventory/bom','/orders/1/accept','/accounting/stock-entry','/orders/1/purchase-request'],
            'accountant':['/accounting/stock-entry','/inventory/components','/orders/1/accept','/orders/1/purchase-request']}
        for role,paths in denied.items():
            self.login_as(role)
            for path in paths:
                with self.subTest(role=role,path=path):
                    self.assertEqual(self.post(path).status_code,403)

    def test_registration_cannot_self_assign_privileged_role(self):
        for role in ('admin','warehouse','purchasing','technician','accountant'):
            self.post('/register',{'name':'X','email':role+'new@test.local','password':'123456','confirm_password':'123456','role':role})
        self.assertEqual(self.sql("SELECT * FROM users WHERE email LIKE '%new@test.local'"),[])
        self.post('/register',{'name':'Sale','email':'new@test.local','password':'123456','confirm_password':'123456','role':'sales'})
        self.assertEqual(self.sql("SELECT role FROM users WHERE email='new@test.local'")[0]['role'],'sales')

    def test_changed_role_is_checked_against_database(self):
        self.login_as('warehouse')
        self.sql("UPDATE users SET role='sales' WHERE id=?",(self.users['warehouse'],))
        self.assertEqual(self.post('/accounting/stock-entry',{'component_id':1,'quantity':1}).status_code,403)

    def test_csrf_is_required_and_tokens_are_rendered(self):
        self.login_as('warehouse')
        self.assertEqual(self.client.post('/accounting/stock-entry',data={'component_id':1,'quantity':1}).status_code,400)
        self.assertIn(b'name="csrf_token"',self.client.get('/inventory/').data)
        self.assertEqual(self.sql('SELECT stock FROM components WHERE id=1')[0]['stock'],100)

    def test_sales_cannot_read_or_cancel_other_users_order(self):
        oid=self.call(create_order,[(1,1)],{'customer_name':'Admin order'},self.users['admin'])
        self.login_as('sales')
        self.assertEqual(self.client.get(f'/orders/{oid}').status_code,404)
        self.assertEqual(self.post(f'/orders/{oid}/cancel').status_code,404)

    def test_changed_bom_and_inactive_product_do_not_rewrite_existing_orders(self):
        oid=self.order()
        self.login_as('technician')
        self.post('/inventory/products/1/toggle')
        with self.assertRaises(ValueError):
            self.order()
        self.assertEqual(self.sql('SELECT COUNT(*) n FROM order_component_requirements WHERE order_id=?',(oid,))[0]['n'],5)

    def test_forecast_names_are_safely_encoded(self):
        self.sql("UPDATE components SET name='<img src=x onerror=alert(1)>' WHERE id=1")
        self.login_as('sales')
        self.assertIn('&lt;img',self.client.get('/inventory/').get_data(as_text=True))
        self.assertNotIn('innerHTML',Path('static/app.js').read_text(encoding='utf-8-sig'))

    def test_all_primary_pages_render_for_all_roles(self):
        for role in self.users:
            self.login_as(role)
            for path in ('/','/orders/','/inventory/'):
                with self.subTest(role=role,path=path):
                    self.assertEqual(self.client.get(path).status_code,200)
            if role in ('admin','warehouse','purchasing','accountant'):
                self.assertEqual(self.client.get('/accounting/').status_code,200)
        self.login_as('admin')
        for path in ('/team','/inventory/audit-history','/orders/new'):
            self.assertEqual(self.client.get(path).status_code,200)

    def test_migration_is_repeatable_preserves_snapshot_and_foreign_keys(self):
        oid=self.order()
        before=self.sql('SELECT * FROM order_component_requirements WHERE order_id=?',(oid,))
        self.sql('UPDATE bom_items SET quantity=99 WHERE bom_id=(SELECT bom_id FROM orders WHERE id=?)',(oid,))
        create_app(self.config(self.database))
        create_app(self.config(self.database))
        self.assertEqual(self.sql('SELECT * FROM order_component_requirements WHERE order_id=?',(oid,)),before)
        self.assertEqual(self.sql('PRAGMA foreign_key_check'),[])
        self.assertEqual(len(self.sql('SELECT * FROM sales_order_items WHERE order_id=?',(oid,))),1)

    def test_large_excel_preview_and_commit_use_bounded_query_count(self):
        file=self.excel([['sku','name','unit']]+[[f'BULK-{i}',f'Component {i}','m'] for i in range(1000)])
        with self.app.app_context():
            db=get_db()
            statements=[]
            db.set_trace_callback(statements.append)
            batch,_,errors=preview_import(file,'components',self.users['admin'])
            self.assertEqual(errors,0)
            self.assertLess(len(statements),30)
            statements.clear()
            commit_import(batch,'components',self.users['admin'])
            self.assertLess(len(statements),30)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM components WHERE sku LIKE 'BULK-%' AND stock=0").fetchone()[0],1000)

    def test_legacy_role_constraint_is_migrated_without_losing_users(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('PRAGMA foreign_keys=OFF')
            db.executescript("""CREATE TABLE old_users(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('admin','sales','technician','accountant')));
                INSERT INTO old_users SELECT * FROM users WHERE role NOT IN ('warehouse','purchasing');
                DROP TABLE users;
                ALTER TABLE old_users RENAME TO users;""")
        create_app(self.config(self.database))
        with self.app.app_context():
            db=get_db()
            db.execute("INSERT INTO users(name,email,password_hash,role) VALUES('Warehouse','new-warehouse@test.local','unused','warehouse')")
            db.commit()
            self.assertEqual(db.execute('PRAGMA foreign_keys').fetchone()[0],1)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0],1)

    def test_non_ascii_csrf_and_extreme_numeric_input_return_client_error(self):
        self.login_as('warehouse')
        with self.client.session_transaction() as session:
            session['_csrf']='ascii'
        self.assertEqual(self.client.post('/accounting/stock-entry',data={'csrf_token':'mã'}).status_code,400)
        self.login_as('sales')
        self.assertEqual(self.post('/orders/check-stock',{'product_id':'9'*100,'quantity':1}).status_code,400)

    def test_inconsistent_legacy_reservation_is_not_spent_or_released(self):
        oid=self.order()
        self.sql("UPDATE orders SET status='accepted',material_status='reserved',accepted_by=? WHERE id=?",(self.users['warehouse'],oid))
        self.sql('UPDATE components SET reserved=1 WHERE id=1')
        with self.assertRaises(ValueError):
            self.call(cancel_order,oid,self.users['admin'],'admin')
        with self.assertRaises(ValueError):
            self.call(advance_order,oid,'installing',self.users['warehouse'],'warehouse')
        self.assertEqual(self.sql('SELECT stock,reserved FROM components WHERE id=1')[0],dict(stock=100,reserved=1))

    def test_empty_production_database_has_no_demo_accounts_and_supports_admin_provisioning(self):
        path=str(Path(self.directory.name)/'production.db')
        config=self.config(path)
        config['SEED_DEMO']=False
        app=create_app(config)
        with app.app_context():
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM users').fetchone()[0],0)
        result=app.test_cli_runner().invoke(args=['create-admin','--name','Owner','--email','owner@test.local'],input='strong-pass-123!\nstrong-pass-123!\n')
        self.assertEqual(result.exit_code,0,result.output)
        self.assertNotIn('strong-pass-123!',result.output)
        with app.app_context():
            self.assertEqual(get_db().execute('SELECT role FROM users').fetchone()[0],'admin')

    def test_new_demo_database_has_no_untracked_reservations(self):
        app=create_app(self.config(str(Path(self.directory.name)/'new-demo.db')))
        with app.app_context():
            db=get_db()
            self.assertEqual(db.execute('SELECT SUM(reserved) FROM components').fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM orders WHERE status NOT IN ('pending')").fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sales_order_items WHERE bom_id IS NULL').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM stock_movements').fetchone()[0],5)

    def test_five_hundred_component_bom_uses_batched_database_operations(self):
        with self.app.app_context():
            db=get_db()
            db.executemany('INSERT INTO components(sku,name,unit,stock) VALUES(?,?,?,?)',[(f'PART-{i}',f'Part {i}','m',100) for i in range(500)])
            db.execute("INSERT INTO products(sku,name,price) VALUES('LARGE-BOM','Large BOM',100)")
            pid=db.execute('SELECT last_insert_rowid()').fetchone()[0]
            ids=[r[0] for r in db.execute("SELECT id FROM components WHERE sku LIKE 'PART-%'")]
            db.commit()
            statements=[]
            db.set_trace_callback(statements.append)
            bom=save_draft(pid,[(cid,'0.25') for cid in ids],self.users['technician'])
            activate_bom(bom,self.users['technician'])
            oid=create_order([(pid,2)],{'customer_name':'Large order'},self.users['sales'])
            reserve_order(oid,self.users['warehouse'])
            self.assertLess(len(statements),80)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM order_component_requirements WHERE order_id=?',(oid,)).fetchone()[0],500)
            self.assertEqual(db.execute("SELECT SUM(reserved) FROM components WHERE sku LIKE 'PART-%'").fetchone()[0],250)

    def test_bom_import_opens_the_created_draft_with_dynamic_lines(self):
        self.login_as('technician')
        batch,_,errors=self.call(preview_import,self.excel([['product_sku','component_sku','quantity'],['SP-001','LK-001',7],['SP-001','LK-002',8]]),'bom',self.users['technician'])
        self.assertEqual(errors,0)
        response=self.post(f'/inventory/imports/bom/{batch}/commit')
        self.assertIn('bom_id=',response.location)
        text=self.client.get(response.location).get_data(as_text=True)
        self.assertIn('Linh kiện 2',text)
        self.assertEqual(self.sql('SELECT import_batch_id FROM boms WHERE import_batch_id=?',(batch,))[0]['import_batch_id'],batch)

    def test_production_is_owned_by_technician_not_warehouse_approver(self):
        oid=self.order()
        self.call(reserve_order,oid,self.users['warehouse'])
        self.call(advance_order,oid,'installing',self.users['warehouse'],'warehouse')
        self.call(advance_order,oid,'testing',self.users['technician'],'technician')
        owner=self.sql('SELECT accepted_by,production_by FROM orders WHERE id=?',(oid,))[0]
        self.assertEqual(owner,dict(accepted_by=self.users['warehouse'],production_by=self.users['technician']))
        self.sql("INSERT INTO users(name,email,password_hash,role) VALUES('Other tech','other-tech@test.local','unused','technician')")
        other=self.sql("SELECT id FROM users WHERE email='other-tech@test.local'")[0]['id']
        with self.assertRaises(ValueError):
            self.call(advance_order,oid,'completed',other,'technician')

    def test_cancelled_orders_are_excluded_from_sales_totals(self):
        from controllers.dashboard import sales_monthly_report
        oid=self.order()
        self.call(cancel_order,oid,self.users['sales'],'sales')
        self.assertEqual(sum(row['total'] for row in self.call(sales_monthly_report,self.users['sales'])),0)

    def test_catalog_create_edit_search_and_soft_deactivation(self):
        self.login_as('technician')
        payload={'sku':'sp-new','name':'New product','price':500,'unit':'bộ','category':'Group',
                 'description':'Description','image_url':'https://example.com/product.png'}
        self.assertEqual(self.post('/inventory/products',payload).status_code,302)
        product=self.sql("SELECT * FROM products WHERE sku='SP-NEW'")[0]
        self.assertEqual(product['unit'],'bộ')
        self.assertEqual(product['image_url'],payload['image_url'])
        payload['name']='Edited product'
        self.post(f"/inventory/products/{product['id']}/edit",payload)
        self.assertIn('Edited product',self.client.get('/inventory/?q=SP-NEW').get_data(as_text=True))
        self.post(f"/inventory/products/{product['id']}/toggle")
        with self.assertRaises(ValueError):
            self.call(check_items,[(product['id'],1)])
        self.login_as('warehouse')
        part={'sku':'lk-new','name':'New part','unit':'m','stock':'2.5','min_stock':'0.5','category_id':1}
        self.assertEqual(self.post('/inventory/components',part).status_code,302)
        component=self.sql("SELECT * FROM components WHERE sku='LK-NEW'")[0]
        self.assertEqual(component['stock'],2.5)
        part['name']='Edited part'
        self.post(f"/inventory/components/{component['id']}/edit",part)
        self.assertEqual(self.sql('SELECT name FROM components WHERE id=?',(component['id'],))[0]['name'],'Edited part')
        part['unit']='kg'
        self.post(f"/inventory/components/{component['id']}/edit",part)
        self.assertEqual(self.sql('SELECT unit FROM components WHERE id=?',(component['id'],))[0]['unit'],'m')
        self.post('/inventory/components',part)
        self.assertEqual(len(self.sql("SELECT * FROM components WHERE UPPER(sku)='LK-NEW'")),1)

    def test_legacy_forecast_does_not_claim_partial_inactive_bom_is_sufficient(self):
        self.sql('UPDATE components SET active=0 WHERE id=1')
        self.login_as('sales')
        response=self.client.get('/inventory/forecast?product_id=1&quantity=1')
        self.assertEqual(response.status_code,422)
        self.assertEqual(response.get_json()['material_status'],'unknown')


if __name__=='__main__':
    unittest.main()
