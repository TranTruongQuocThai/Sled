const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('../.venv/frontend-tests/node_modules/jsdom');
const script=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
const fixture=name=>fs.readFileSync(path.join(__dirname,'../.venv/frontend-tests',name),'utf8');
const green={items:[],requirements:[{sku:'LK-1',name:'Motor',required:1,available:10,shortage:0,unit:'cái'}],material_status:'pending_approval',invalid_products:[]};
const red={...green,material_status:'pending_material',requirements:[{...green.requirements[0],required:20,shortage:10}]};
const response=data=>({ok:true,json:async()=>data});
const settle=()=>new Promise(resolve=>setImmediate(resolve));
async function view(name,fetcher=async()=>response(green)){
  const dom=new JSDOM(fixture(name),{url:'http://localhost/',runScripts:'outside-only'});
  const w=dom.window;
  const timers=new Map();
  let seq=0;
  w.setTimeout=callback=>{timers.set(++seq,callback);return seq;};
  w.clearTimeout=id=>timers.delete(id);
  w.fetch=fetcher;
  w.eval(script);
  if(w.document.readyState==='loading') await new Promise(resolve=>w.document.addEventListener('DOMContentLoaded',resolve,{once:true}));
  await settle();
  return {dom,w,doc:w.document,flush:async()=>{const callbacks=[...timers.values()];timers.clear();callbacks.forEach(cb=>cb());await settle();}};
}

test('all rendered pages have valid dialog, tab and protected form connections',()=>{
  const files=fs.readdirSync(path.join(__dirname,'../.venv/frontend-tests')).filter(x=>x.endsWith('.html'));
  assert.ok(files.length>=30);
  for(const name of files){
    const dom=new JSDOM(fixture(name));const doc=dom.window.document;
    assert.equal(doc.compatMode,'CSS1Compat',name);
    const ids=[...doc.querySelectorAll('[id]')].map(x=>x.id);
    assert.equal(new Set(ids).size,ids.length,`duplicate IDs in ${name}`);
    for(const opener of doc.querySelectorAll('[data-open-dialog]')) assert.equal(doc.getElementById(opener.dataset.openDialog)?.tagName,'DIALOG',`${name}: ${opener.dataset.openDialog}`);
    for(const tab of doc.querySelectorAll('[role="tab"]')){
      const panel=doc.getElementById(tab.getAttribute('aria-controls'));
      assert.equal(panel?.getAttribute('role'),'tabpanel',`${name}: ${tab.id}`);
      assert.equal(panel.getAttribute('aria-labelledby'),tab.id);
    }
    for(const form of doc.querySelectorAll('form[method="post"]')){
      assert.ok(form.querySelector('input[name="csrf_token"]')?.value,`CSRF in ${name}`);
      assert.equal(form.querySelector('form'),null,`nested form in ${name}`);
    }
    assert.equal(doc.querySelectorAll('script:not([src])').length,0,name);
    dom.window.close();
  }
});

test('login and registration show no sample credentials or prefilled password',()=>{
  for(const name of ['login.html','register.html']){
    const dom=new JSDOM(fixture(name));const doc=dom.window.document;
    assert.doesNotMatch(doc.body.textContent,/Tài khoản mẫu|khoflow\.local|Manager123|Sale123|Tho123/i);
    for(const input of doc.querySelectorAll('input[type="password"],input[type="email"]')) assert.equal(input.value,'');
    assert.ok(doc.querySelector('link[href*="workflows.css"]'));
    dom.window.close();
  }
});

test('cards open dialogs, Escape closes and returns keyboard focus',async t=>{
  const v=await view('inventory-admin.html');t.after(()=>v.w.close());
  const opener=v.doc.querySelector('[data-open-dialog="product-1"]');
  opener.focus();opener.click();
  const dialog=v.doc.getElementById('product-1');
  assert.ok(dialog.open);assert.ok(dialog.contains(v.doc.activeElement));
  assert.equal(v.doc.activeElement.closest('[hidden]'),null);
  v.doc.activeElement.dispatchEvent(new v.w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  assert.equal(dialog.open,false);assert.equal(v.doc.activeElement,opener);
  assert.equal(v.doc.body.classList.contains('modal-open'),false);
});

test('nested tabs change only their own panels and support arrow keys',async t=>{
  const v=await view('inventory-admin.html');t.after(()=>v.w.close());
  v.doc.querySelector('[data-open-dialog="import-excel"]').click();
  const tab=v.doc.getElementById('import-components-tab');tab.focus();
  tab.dispatchEvent(new v.w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
  assert.equal(v.doc.getElementById('import-bom-tab').getAttribute('aria-selected'),'true');
  assert.equal(v.doc.getElementById('import-bom-panel').hidden,false);
  assert.equal(v.doc.getElementById('import-components-panel').hidden,true);
  assert.equal(v.doc.getElementById('panel-products').hidden,false);
  assert.equal(v.doc.getElementById('panel-components').hidden,true);
});

test('search matches Vietnamese accents and pagination resets for a new query',async t=>{
  const v=await view('orders-sales.html');t.after(()=>v.w.close());
  const scope=v.doc.querySelector('[data-filter]');
  const visible=()=>[...scope.querySelectorAll('[data-filter-item]')].filter(x=>!x.hidden);
  assert.equal(visible().length,12);
  scope.querySelector('[data-page="next"]').click();
  assert.equal(visible().length,6);
  const search=scope.querySelector('[data-filter-input]');search.value='dang minh 0';
  search.dispatchEvent(new v.w.Event('input',{bubbles:true}));
  assert.equal(visible().length,1);assert.match(visible()[0].textContent,/Đặng Minh 0/);
  assert.equal(scope.querySelector('[data-pagination]').hidden,true);
  search.value='no-matching-order';search.dispatchEvent(new v.w.Event('input',{bubbles:true}));
  assert.equal(visible().length,0);assert.equal(scope.querySelector('[data-filter-empty]').hidden,false);
});

test('dashboard ready link applies the material filter without including shortages',async t=>{
  const v=await view('orders-ready.html');t.after(()=>v.w.close());
  const active=v.doc.querySelector('[data-filter-value].is-active');
  assert.equal(active.dataset.filterValue,'pending_approval');
  const visible=[...v.doc.querySelectorAll('[data-filter-item]')].filter(x=>!x.hidden);
  assert.ok(visible.length>0);
  assert.ok(visible.every(x=>x.dataset.filterTags.includes('pending_approval')));
});

test('clearing a linked catalog search restores all records and other tabs remain independent',async t=>{
  const v=await view('inventory-filtered.html');t.after(()=>v.w.close());
  const products=v.doc.getElementById('panel-products');
  const search=products.querySelector('[data-filter-input]');
  const visible=()=>[...products.querySelectorAll('[data-filter-item]')].filter(x=>!x.hidden);
  assert.equal(search.value,'SP-002');assert.equal(visible().length,1);
  search.value='';search.dispatchEvent(new v.w.Event('input',{bubbles:true}));
  assert.equal(visible().length,2);
  v.doc.getElementById('tab-components').click();
  const components=v.doc.getElementById('panel-components');
  assert.equal(components.querySelector('[data-filter-input]').value,'');
  assert.ok([...components.querySelectorAll('[data-filter-item]')].some(x=>!x.hidden));
});

test('closing confirmation never submits and confirming submits once to the original route',async t=>{
  const v=await view('order-detail.html');t.after(()=>v.w.close());
  const form=v.doc.querySelector('form[data-confirm]');const submitter=form.querySelector('button');
  let count=0;
  form.requestSubmit=button=>{assert.equal(button,submitter);const event=new v.w.SubmitEvent('submit',{bubbles:true,cancelable:true,submitter:button});form.dispatchEvent(event);if(!event.defaultPrevented)count++;};
  const attempt=()=>form.dispatchEvent(new v.w.SubmitEvent('submit',{bubbles:true,cancelable:true,submitter}));
  assert.equal(attempt(),false);assert.equal(count,0);
  v.doc.querySelector('#confirm-action [data-close-dialog]').click();assert.equal(count,0);
  attempt();v.doc.getElementById('confirm-submit').click();assert.equal(count,1);
  assert.equal(v.doc.getElementById('confirm-action').open,false);
  attempt();v.doc.getElementById('confirm-submit').click();assert.equal(count,1);
});

test('remote order popup loads real detail with working nested tabs',async t=>{
  const calls=[];
  const v=await view('orders-admin.html',async url=>{calls.push(url);return {ok:true,text:async()=>fixture('order-detail.html')};});t.after(()=>v.w.close());
  v.doc.querySelector('[data-remote-dialog]').click();await settle();
  assert.equal(calls.length,1);assert.ok(v.doc.getElementById('remote-dialog').open);
  const fragment=v.doc.querySelector('#remote-dialog-content [data-dialog-fragment]');assert.ok(fragment);
  const materials=fragment.querySelector('[data-tab$="materials"]');materials.click();
  assert.equal(fragment.querySelector('[data-panel$="materials"]').hidden,false);
  assert.equal(fragment.querySelector('[data-panel$="information"]').hidden,true);
  assert.ok(fragment.querySelector('form[action$="/cancel"] input[name="csrf_token"]'));
});

test('closing a remote popup prevents a slow response from adding content',async t=>{
  let resolve;
  const v=await view('orders-admin.html',()=>new Promise(done=>{resolve=done;}));t.after(()=>v.w.close());
  v.doc.querySelector('[data-remote-dialog]').click();
  v.doc.querySelector('#remote-dialog [data-close-dialog]').click();
  resolve({ok:true,text:async()=>fixture('order-detail.html')});await settle();
  assert.equal(v.doc.getElementById('remote-dialog').open,false);
  assert.equal(v.doc.querySelector('#remote-dialog-content [data-dialog-fragment]'),null);
});

test('Excel preview shows safe row errors in a nested dialog and blocks invalid commit',async t=>{
  const v=await view('preview-error.html');t.after(()=>v.w.close());
  const preview=v.doc.getElementById('preview-rows');assert.ok(preview.open);
  assert.equal(v.doc.querySelector('form[action$="/commit"]'),null);
  const opener=preview.querySelector('[data-message]');opener.click();
  const error=v.doc.getElementById('row-error');assert.ok(error.open);
  assert.match(error.querySelector('[data-dialog-message]').textContent,/Dòng 3: Trùng mã/);
  error.querySelector('[data-close-dialog]').click();
  assert.ok(preview.open);assert.equal(v.doc.activeElement,opener);
  preview.querySelector('[data-filter-value="error"]').click();
  assert.equal([...preview.querySelectorAll('[data-filter-item]')].filter(x=>!x.hidden).length,1);
});

test('unsaved BOM changes disable activation until the draft has been saved',async t=>{
  const v=await view('bom-draft.html');t.after(()=>v.w.close());
  const activate=v.doc.querySelector('[data-activate-bom]');assert.equal(activate.disabled,false);
  const qty=v.doc.querySelector('[data-bom-editor] [name="quantity"]');qty.value='5';qty.dispatchEvent(new v.w.Event('input',{bubbles:true}));
  assert.equal(activate.disabled,true);assert.match(v.doc.querySelector('[data-bom-save-hint]').textContent,/chưa lưu/);
});

test('stock and purchasing actions follow the separated roles',()=>{
  for(const role of ['warehouse','purchasing','accountant']){
    const dom=new JSDOM(fixture(`accounting-${role}.html`));const doc=dom.window.document;
    assert.equal(!!doc.querySelector('form[action$="/stock-entry"]'),role==='warehouse');
    assert.equal(!!doc.querySelector('form[action$="/receive"]'),role==='warehouse');
    assert.equal(!!doc.querySelector('form[action$="/cancel"]'),role==='purchasing');
    dom.window.close();
  }
});

test('forecast total uses returned line quantities and resets when edited',async t=>{
  const v=await view('order.html',async()=>response({...green,items:[{price:18000000,quantity:2},{price:1000,quantity:3}]}));t.after(()=>v.w.close());
  assert.equal(v.doc.getElementById('order-total').textContent,'36.003.000 ₫');
  v.doc.querySelector('[name="quantity"]').dispatchEvent(new v.w.Event('input',{bubbles:true}));
  assert.equal(v.doc.getElementById('order-total').textContent,'—');
});

test('BOM can add and delete lines while preserving all other values',async t=>{
  const v=await view('bom.html');t.after(()=>v.dom.window.close());
  const list=v.doc.querySelector('[data-repeat-list="bom"]');
  const add=v.doc.querySelector('[data-add-row="bom"]');
  add.click();add.click();
  const rows=[...list.querySelectorAll('[data-repeat-row]')];
  rows[0].querySelector('input').value='4';
  rows[1].querySelector('input').value='7';
  rows[2].querySelector('input').value='9';
  rows[2].querySelector('select').value='3';
  rows[1].querySelector('[data-remove-row]').click();
  assert.deepEqual([...list.querySelectorAll('input')].map(x=>x.value),['4','9']);
  assert.deepEqual([...list.querySelectorAll('select')].map(x=>x.value),['1','3']);
  assert.match(list.lastElementChild.querySelector('strong').textContent,/2$/);
  list.lastElementChild.querySelector('[data-remove-row]').click();
  list.firstElementChild.querySelector('[data-remove-row]').click();
  assert.equal(list.children.length,1);
});

test('BOM supports more than one hundred dynamic lines',async t=>{
  const v=await view('bom.html');t.after(()=>v.dom.window.close());
  const add=v.doc.querySelector('[data-add-row="bom"]');
  for(let i=0;i<149;i++)add.click();
  const list=v.doc.querySelector('[data-repeat-list="bom"]');
  assert.equal(list.children.length,150);
  list.children[73].querySelector('input').value='12';
  list.children[72].querySelector('[data-remove-row]').click();
  assert.equal(list.children[72].querySelector('input').value,'12');
});

test('multi-product forecast submits all lines and the CSRF token',async t=>{
  const calls=[];
  const v=await view('order.html',async(url,opts)=>{calls.push({url,opts});return response(green);});
  t.after(()=>v.dom.window.close());
  const list=v.doc.querySelector('[data-repeat-list="order"]');
  list.firstElementChild.querySelector('input').value='3';
  v.doc.querySelector('[data-add-row="order"]').click();
  list.lastElementChild.querySelector('select').value='2';
  list.lastElementChild.querySelector('input').value='5';
  await v.flush();
  const call=calls.at(-1);
  assert.equal(call.url,'/orders/check-stock');
  assert.deepEqual([...call.opts.body.getAll('product_id')],['1','2']);
  assert.deepEqual([...call.opts.body.getAll('quantity')],['3','5']);
  assert.equal(call.opts.headers['X-CSRF-Token'],call.opts.body.get('csrf_token'));
  assert.ok(v.doc.querySelector('#forecast .pending_approval'));
});

test('editing a quantity clears the old green result before debounce',async t=>{
  const v=await view('order.html');t.after(()=>v.dom.window.close());
  assert.ok(v.doc.querySelector('#forecast .pending_approval'));
  const qty=v.doc.querySelector('[name="quantity"]');
  qty.value='100';qty.dispatchEvent(new v.w.Event('input',{bubbles:true}));
  assert.equal(v.doc.querySelector('#forecast .pending_approval'),null);
  assert.ok(v.doc.querySelector('#forecast .unknown'));
});

test('a stale successful response cannot replace a newer shortage result',async t=>{
  const pending=[];
  const v=await view('order.html',()=>new Promise(resolve=>pending.push(resolve)));
  t.after(()=>v.dom.window.close());
  assert.equal(pending.length,1);
  const qty=v.doc.querySelector('[name="quantity"]');
  qty.value='20';qty.dispatchEvent(new v.w.Event('input',{bubbles:true}));
  await v.flush();
  assert.equal(pending.length,2);
  pending[1](response(red));await settle();
  assert.ok(v.doc.querySelector('#forecast .pending_material'));
  pending[0](response(green));await settle();
  assert.ok(v.doc.querySelector('#forecast .pending_material'));
  assert.equal(v.doc.querySelector('#forecast .pending_approval'),null);
});

test('component names render as text without executing HTML',async t=>{
  const malicious={...green,requirements:[{...green.requirements[0],name:'<img src=x onerror="alert(1)">'}]};
  const v=await view('order.html',async()=>response(malicious));t.after(()=>v.dom.window.close());
  assert.equal(v.doc.querySelector('#forecast img'),null);
  assert.match(v.doc.querySelector('#forecast').textContent,/<img/);
});

test('missing BOM and network errors are shown as unknown',async t=>{
  const missing={...green,requirements:[],material_status:'unknown',invalid_products:['NO-BOM']};
  const v=await view('order.html',async()=>response(missing));t.after(()=>v.dom.window.close());
  assert.ok(v.doc.querySelector('#forecast .unknown'));
  assert.match(v.doc.querySelector('#forecast').textContent,/NO-BOM/);
  v.w.fetch=async()=>{throw new Error('offline');};
  const qty=v.doc.querySelector('[name="quantity"]');
  qty.dispatchEvent(new v.w.Event('input',{bubbles:true}));await v.flush();
  assert.ok(v.doc.querySelector('#forecast .unknown'));
  assert.match(v.doc.querySelector('#forecast').textContent,/offline/);
});
