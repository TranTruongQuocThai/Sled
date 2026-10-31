"""Render the real application views for the DOM regression suite."""
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
sys.path.insert(0,str(root/'tests'))
from test_workflows import WorkflowTests
from models.workflows import request_purchase, save_draft

output=root/'.venv'/'frontend-tests'
output.mkdir(parents=True,exist_ok=True)
WorkflowTests.setUpClass()
test=WorkflowTests('test_all_primary_pages_render_for_all_roles')
try:
    test.setUp()
    oid=test.order()
    for index in range(16):
        extra=test.order()
        test.sql('UPDATE orders SET customer_name=? WHERE id=?',(f'Đặng Minh {index}',extra))
    shortage=test.order([(1,200)])
    test.call(request_purchase,shortage,test.users['purchasing'])
    draft=test.call(save_draft,1,[(1,1),(2,2)],test.users['technician'])
    views=[('sales','/orders/new','order.html'),('technician','/inventory/','bom.html'),
           ('admin',f'/inventory/?bom_id={draft}','bom-draft.html'),
           ('admin','/inventory/?section=products&q=SP-002','inventory-filtered.html'),
           ('admin',f'/orders/{oid}','order-detail.html'),('sales',f'/orders/{oid}/edit','order-edit.html'),
           ('sales','/orders/?status=pending_approval','orders-ready.html'),
           ('sales','/reports','reports.html'),('admin','/team','team.html')]
    for role in ('admin','sales','technician','warehouse','purchasing','accountant'):
        views.extend([(role,'/',f'home-{role}.html'),(role,'/inventory/',f'inventory-{role}.html'),
                      (role,'/orders/',f'orders-{role}.html')])
        if role in ('admin','warehouse','purchasing','accountant'):
            views.append((role,'/accounting/',f'accounting-{role}.html'))
    for role,url,name in views:
        test.login_as(role)
        response=test.client.get(url)
        assert response.status_code==200
        (output/name).write_bytes(response.data)
    test.login_as('admin')
    valid=[['sku','name','unit','category'],['NEW-1','Động cơ bổ sung','cái','Động cơ']]
    invalid=valid+[['NEW-1','Trùng mã','cái','Động cơ']]
    for rows,name in [(valid,'preview-valid.html'),(invalid,'preview-error.html')]:
        file=test.excel(rows)
        response=test.post('/inventory/imports/components/preview',{'file':(file.stream,file.filename)})
        assert response.status_code==200
        (output/name).write_bytes(response.data)
    response=test.client.get('/inventory/audit-history?tab=imports')
    assert response.status_code==200
    (output/'audit.html').write_bytes(response.data)
    with test.client.session_transaction() as session:
        session.clear()
    for route in ('login','register'):
        response=test.client.get('/'+route)
        assert response.status_code==200
        (output/(route+'.html')).write_bytes(response.data)
finally:
    test.tearDown()
    WorkflowTests.tearDownClass()
print('Rendered isolated views for frontend regression tests.')
