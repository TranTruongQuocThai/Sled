import React, { useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { LayoutDashboard, Package, ClipboardList, Users, Settings, Search, Bell, ChevronDown, Plus, ArrowUpRight, AlertTriangle, CheckCircle2, ShoppingCart, X, Menu } from 'lucide-react'
import './styles.css'

const inventory = [
  { id: 'LK-001', name: 'Khung nhôm 6061', unit: 'cái', stock: 42, reserved: 8, min: 15, status: 'Đủ hàng' },
  { id: 'LK-002', name: 'Bánh xe 80mm', unit: 'cái', stock: 116, reserved: 24, min: 40, status: 'Đủ hàng' },
  { id: 'LK-003', name: 'Motor DC 24V', unit: 'cái', stock: 18, reserved: 6, min: 20, status: 'Sắp hết' },
  { id: 'LK-004', name: 'Bộ điều khiển M1', unit: 'bộ', stock: 27, reserved: 3, min: 10, status: 'Đủ hàng' },
  { id: 'LK-005', name: 'Pin lithium 24V', unit: 'bộ', stock: 11, reserved: 2, min: 12, status: 'Sắp hết' },
]
const bom = [
  { part: 'Khung nhôm 6061', code: 'LK-001', qty: 1 },
  { part: 'Bánh xe 80mm', code: 'LK-002', qty: 4 },
  { part: 'Motor DC 24V', code: 'LK-003', qty: 2 },
  { part: 'Bộ điều khiển M1', code: 'LK-004', qty: 1 },
  { part: 'Pin lithium 24V', code: 'LK-005', qty: 1 },
]
const initialOrders = [
  { id: 'DH-24091', customer: 'Công ty An Phát', product: 'Xe đẩy tự hành S1', qty: 3, value: '54.000.000đ', owner: 'Nguyễn Minh Anh', date: '12/09/2026', status: 'Chờ duyệt' },
  { id: 'DH-24087', customer: 'Kho vận Đại Nam', product: 'Xe đẩy tự hành S1', qty: 2, value: '36.000.000đ', owner: 'Nguyễn Minh Anh', date: '10/09/2026', status: 'Đã xác nhận' },
  { id: 'DH-24084', customer: 'Cơ khí Hoàng Long', product: 'Xe đẩy tự hành S1', qty: 5, value: '90.000.000đ', owner: 'Trần Quốc Huy', date: '08/09/2026', status: 'Đang sản xuất' },
]
const users = [
  { name: 'Nguyễn Minh Anh', role: 'Sale', initials: 'MA', color: '#e9a16c' },
  { name: 'Trần Quốc Huy', role: 'Admin', initials: 'QH', color: '#5b78c7' },
  { name: 'Lê Gia Bảo', role: 'Thợ', initials: 'GB', color: '#5eaf94' },
]

function App() {
  const [currentUser, setCurrentUser] = useState(users[0])
  const [page, setPage] = useState('Tổng quan')
  const [orderQty, setOrderQty] = useState(3)
  const [orders, setOrders] = useState(initialOrders)
  const [modal, setModal] = useState(false)
  const [menu, setMenu] = useState(false)
  const [form, setForm] = useState({ customer: '', phone: '', address: '', product: 'Xe đẩy tự hành S1', qty: 1, note: '' })
  const needs = useMemo(() => bom.map(item => {
    const part = inventory.find(x => x.id === item.code)
    const required = item.qty * Number(orderQty || 0)
    const remain = part.stock - part.reserved - required
    return { ...item, required, available: part.stock - part.reserved, remain, issue: remain < 0 }
  }), [orderQty])
  const nav = [
    ['Tổng quan', LayoutDashboard], ['Kho linh kiện', Package], ['Đơn hàng', ClipboardList], ['Nhân sự', Users], ['Cài đặt', Settings]
  ]
  // Invoice access is enforced at the view layer: managers see all, each sale sees
  // only their own invoices, and technicians do not have invoice access.
  const privateOrders = currentUser.role === 'Admin' ? orders : currentUser.role === 'Sale' ? orders.filter(o => o.owner === currentUser.name) : []
  const visibleNav = currentUser.role === 'Sale' ? nav.filter(([label]) => label === 'Tổng quan' || label === 'Đơn hàng') : nav
  const createOrder = e => {
    e.preventDefault()
    const newOrder = { id: `DH-${24100 + orders.length}`, customer: form.customer || 'Khách hàng mới', product: form.product, qty: Number(form.qty), value: `${(Number(form.qty) * 18000000).toLocaleString('vi-VN')}đ`, owner: currentUser.name, date: 'Hôm nay', status: 'Chờ duyệt' }
    setOrders([newOrder, ...orders]); setModal(false); setForm({ customer: '', phone: '', address: '', product: 'Xe đẩy tự hành S1', qty: 1, note: '' }); setPage('Đơn hàng')
  }
  return <div className="app">
    <aside className={menu ? 'sidebar open' : 'sidebar'}>
      <div className="brand"><div className="brand-mark"><span></span><span></span><span></span></div><span>SLED</span></div>
      <div className="workspace"><span className="tiny">KHÔNG GIAN LÀM VIỆC</span><div className="workspace-name">Xưởng Sản xuất SLED <ChevronDown size={14}/></div></div>
      <nav>{visibleNav.map(([label, Icon]) => <button key={label} className={page === label ? 'active' : ''} onClick={() => {setPage(label);setMenu(false)}}><Icon size={19}/><span>{label}</span>{label === 'Đơn hàng' && currentUser.role === 'Sale' && <i>{privateOrders.length}</i>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="help-card"><span>?</span><div><b>Cần hỗ trợ?</b><small>Trung tâm trợ giúp</small></div></div><div className="role-note"><CheckCircle2 size={16}/><span>Phiên làm việc an toàn</span></div></div>
    </aside>
    <main>
      <header><button className="mobile-menu" onClick={() => setMenu(!menu)}><Menu/></button><div><h1>{page}</h1><p>{page === 'Tổng quan' ? 'Theo dõi hoạt động kho hôm nay' : page === 'Đơn hàng' ? 'Quản lý đơn hàng và thông tin khách hàng' : 'Quản lý dữ liệu vận hành'}</p></div><div className="header-actions"><button className="icon-btn"><Search size={20}/></button><button className="icon-btn notification"><Bell size={20}/><em></em></button><div className="divider"></div><button className="profile" onClick={() => { const nextUser = users[(users.indexOf(currentUser)+1)%users.length]; setCurrentUser(nextUser); setPage('Tổng quan') }}><div className="avatar" style={{background: currentUser.color}}>{currentUser.initials}</div><div className="profile-name"><b>{currentUser.name}</b><small>{currentUser.role}</small></div><ChevronDown size={15}/></button></div></header>
      <section className="content">
        {page === 'Tổng quan' && <Dashboard inventory={inventory} orders={privateOrders} user={currentUser} setPage={setPage} setModal={setModal}/>} 
        {page === 'Kho linh kiện' && <Inventory />}
        {page === 'Đơn hàng' && <Orders orders={privateOrders} user={currentUser} setModal={setModal}/>} 
        {page === 'Nhân sự' && <People />}
        {page === 'Cài đặt' && <SettingsPage />}
        {currentUser.role !== 'Sale' && (page === 'Tổng quan' || page === 'Đơn hàng') && <section className="calculator"><div className="section-heading"><div><span className="eyebrow">DỰ BÁO SẢN XUẤT</span><h2>Tính linh kiện theo đơn hàng</h2><p>Kiểm tra tồn kho trước khi xác nhận đơn.</p></div><label className="quantity">Số lượng đơn <div><button onClick={()=>setOrderQty(Math.max(1,orderQty-1))}>−</button><input value={orderQty} onChange={e=>setOrderQty(e.target.value)}/><button onClick={()=>setOrderQty(Number(orderQty)+1)}>+</button></div></label></div><div className="need-table"><div className="table-header"><span>Linh kiện</span><span>Cần dùng</span><span>Khả dụng</span><span>Sau đơn</span></div>{needs.map(n=><div className="need-row" key={n.code}><div><b>{n.part}</b><small>{n.code} · {n.qty} / sản phẩm</small></div><b>{n.required} <small>cái</small></b><span>{n.available} cái</span><span className={n.issue?'danger':'success'}>{n.remain} cái {n.issue && <AlertTriangle size={15}/>}</span></div>)}</div></section>}
      </section>
    </main>
    {modal && <OrderModal form={form} setForm={setForm} onClose={()=>setModal(false)} createOrder={createOrder} user={currentUser}/>} 
  </div>
}

function Dashboard({inventory, orders, user, setPage, setModal}) { const low=inventory.filter(x=>x.status==='Sắp hết'); const sales=user.role==='Sale'; return <><div className="welcome"><div><span className="eyebrow">15 THÁNG 9, 2026</span><h2>Chào buổi sáng, {user.name.split(' ').at(-1)} <span>👋</span></h2><p>Đây là tình hình vận hành kho của bạn hôm nay.</p></div>{user.role !== 'Thợ' && <button className="primary" onClick={()=>setModal(true)}><Plus size={18}/> Tạo đơn hàng</button>}</div><div className={'metrics '+(sales?'sales-metrics':'')}><Metric label="Đơn hàng hôm nay" value={orders.length.toString().padStart(2,'0')} note="so với hôm qua" up/>{!sales && <><Metric label="Linh kiện trong kho" value="214" note="mã linh kiện"/><Metric label="Cần nhập thêm" value={low.length.toString().padStart(2,'0')} note="mã dưới định mức" warn/><Metric label="Giá trị đơn hàng" value="90M" note="trong tháng này" up/></>}</div><div className={'grid '+(sales?'sales-dashboard-grid':'')}><section className="card orders-card"><div className="card-title"><div><h3>Đơn hàng gần đây</h3><p>{sales ? 'Chỉ các đơn hàng do bạn tạo' : 'Cập nhật mới nhất từ hệ thống'}</p></div><button className="text-button" onClick={()=>setPage('Đơn hàng')}>Xem tất cả <ArrowUpRight size={16}/></button></div>{orders.slice(0,3).map(o=><div className="order-line" key={o.id}><div className="order-symbol"><ShoppingCart size={17}/></div><div className="order-info"><b>{o.customer}</b><span>{o.id} · {o.qty} sản phẩm</span></div><div className="order-side"><b>{o.value}</b><span className={'pill '+o.status.replaceAll(' ','')}>{o.status}</span></div></div>)}</section>{!sales && <section className="card warning-card"><div className="card-title"><div><h3>Cảnh báo tồn kho</h3><p>Linh kiện cần được chú ý</p></div><span className="alert-count">{low.length}</span></div>{low.map(x=><div className="stock-line" key={x.id}><div><b>{x.name}</b><span>{x.id}</span></div><div><b>{x.stock} <small>{x.unit}</small></b><span>Định mức: {x.min}</span></div><AlertTriangle size={19}/></div>)}<button className="outline" onClick={()=>setPage('Kho linh kiện')}>Kiểm tra kho</button></section>}</div></> }
function Metric({label,value,note,up,warn}) {return <div className="metric"><div className={'metric-icon '+(warn?'orange':'')}><Package size={19}/></div><p>{label}</p><strong>{value}</strong><span className={up?'up':''}>{up?'↑ 12% ':''}{note}</span></div>}
function Inventory(){return <section className="card inventory-card"><div className="card-title"><div><h3>Danh mục linh kiện</h3><p>Trạng thái tồn kho theo thời gian thực</p></div><button className="primary"><Plus size={17}/> Thêm linh kiện</button></div><div className="inventory-head"><span>Mã / Tên linh kiện</span><span>Tồn kho</span><span>Đã giữ</span><span>Trạng thái</span></div>{inventory.map(x=><div className="inventory-row" key={x.id}><div><b>{x.name}</b><small>{x.id}</small></div><b>{x.stock} {x.unit}</b><span>{x.reserved} {x.unit}</span><span className={x.status==='Sắp hết'?'pill red':'pill green'}>{x.status}</span></div>)}</section>}
function Orders({orders,user,setModal}){return <section className="card inventory-card"><div className="card-title"><div><h3>{user.role==='Sale'?'Đơn hàng của tôi':'Tất cả đơn hàng'}</h3><p>{user.role==='Sale'?'Các hóa đơn này chỉ hiển thị cho tài khoản của bạn.':'Danh sách đơn hàng trong xưởng.'}</p></div>{user.role !== 'Thợ' && <button className="primary" onClick={()=>setModal(true)}><Plus size={17}/> Tạo đơn hàng</button>}</div>{orders.map(o=><div className="invoice" key={o.id}><div className="invoice-icon"><ClipboardList size={20}/></div><div><b>{o.customer}</b><small>{o.id} · {o.product} · {o.qty} sản phẩm</small></div><div className="invoice-owner"><small>Người tạo</small><b>{o.owner}</b></div><div><b>{o.value}</b><small>{o.date}</small></div><span className={'pill '+o.status.replaceAll(' ','')}>{o.status}</span></div>)}{!orders.length&&<div className="empty">Chưa có đơn hàng nào.</div>}</section>}
function People(){return <section className="card inventory-card"><div className="card-title"><div><h3>Phân quyền nhân sự</h3><p>Mỗi vai trò được cấp đúng quyền cần thiết để làm việc.</p></div></div>{users.map(u=><div className="invoice" key={u.name}><div className="avatar" style={{background:u.color}}>{u.initials}</div><div><b>{u.name}</b><small>Tài khoản đang hoạt động</small></div><div className="role-perms">{u.role==='Admin'?'Toàn quyền · Xem mọi đơn & nhân sự':u.role==='Sale'?'Tạo & xem đơn của mình · Xem kho':'Xem tồn kho · Nhận việc sản xuất'}</div><span className="pill green">{u.role}</span></div>)}</section>}
function SettingsPage(){return <section className="card settings"><h3>Cài đặt xưởng</h3><p>Thiết lập quy tắc cảnh báo tồn kho, luồng duyệt đơn và quyền truy cập.</p><div className="setting-item"><div><b>Riêng tư hóa đơn của sale</b><small>Sale chỉ có thể xem hóa đơn do chính mình tạo.</small></div><span className="toggle on"></span></div><div className="setting-item"><div><b>Cảnh báo tồn kho thấp</b><small>Gửi thông báo khi linh kiện dưới định mức.</small></div><span className="toggle on"></span></div></section>}
function OrderModal({form,setForm,onClose,createOrder,user}){const change=(k,v)=>setForm({...form,[k]:v});return <div className="overlay"><form className="modal" onSubmit={createOrder}><div className="modal-head"><div><span className="eyebrow">TẠO ĐƠN HÀNG</span><h2>Thông tin đơn hàng</h2><p>Đơn sẽ được lưu riêng trong tài khoản {user.name}.</p></div><button type="button" onClick={onClose}><X/></button></div><div className="form-grid"><label>Tên khách hàng<input required placeholder="VD: Công ty An Phát" value={form.customer} onChange={e=>change('customer',e.target.value)}/></label><label>Số điện thoại<input placeholder="0900 000 000" value={form.phone} onChange={e=>change('phone',e.target.value)}/></label><label className="wide">Địa chỉ giao hàng<input placeholder="Nhập địa chỉ giao hàng" value={form.address} onChange={e=>change('address',e.target.value)}/></label><label>Sản phẩm<select value={form.product} onChange={e=>change('product',e.target.value)}><option>Xe đẩy tự hành S1</option><option>Xe đẩy tự hành S2</option></select></label><label>Số lượng<input required type="number" min="1" value={form.qty} onChange={e=>change('qty',e.target.value)}/></label><label className="wide">Ghi chú<textarea placeholder="Yêu cầu đặc biệt của khách hàng" value={form.note} onChange={e=>change('note',e.target.value)}/></label></div><div className="modal-footer"><button type="button" className="cancel" onClick={onClose}>Hủy</button><button className="primary">Lưu đơn hàng <ArrowUpRight size={17}/></button></div></form></div>}
createRoot(document.getElementById('root')).render(<App />)
