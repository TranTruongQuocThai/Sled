# SLED – Luồng nghiệp vụ hiện tại

Ứng dụng chạy bằng Flask/Jinja. Local dùng SQLite; Vercel dùng Turso. Xem kết quả đối chiếu yêu cầu tại [REVIEW-PA.md](REVIEW-PA.md).

## Các vùng mã nguồn

| Phần | Vị trí |
| --- | --- |
| Khởi tạo app, cấu hình, CSRF | `app.py`, `models/security.py` |
| Database và migration tương thích | `models/repository.py`, `migrate_workflows` trong `models/workflows.py` |
| BOM, snapshot đơn, giữ/hủy/xuất kho, mua hàng | `models/workflows.py` |
| Đọc Excel, preview, commit theo lô | `models/excel_imports.py` |
| HTTP / giao diện | `controllers/`, `templates/`, `static/` |
| Tài nguyên CDN Vercel | `public/static/`, phải khớp với `static/` |
| Hồi quy nghiệp vụ / DOM | `tests/test_workflows.py`, `tests/test_ui.cjs` |

`legacy-ui/` là prototype riêng, không phải giao diện của Flask.

## Vai trò

| Việc | Admin | Kỹ thuật / Thợ | Kho | Sale | Mua hàng | Kế toán |
| --- | --- | --- | --- | --- | --- | --- |
| Xem sản phẩm, linh kiện, khả năng sản xuất | Có | Có | Có | Có | Có | Có |
| Sản phẩm, BOM nháp, kích hoạt/import BOM | Có | Có | Không | Không | Không | Không |
| Danh mục/import linh kiện, kiểm kê, nhập kho | Có | Không | Có | Không | Không | Không |
| Tạo/sửa thông tin khách hàng của đơn | Có | Không | Không | Đơn mình | Không | Không |
| Duyệt và giữ vật tư | Có | Không | Có | Không | Không | Không |
| Xuất vật tư để bắt đầu sản xuất | Có | Không | Có | Không | Không | Không |
| Cập nhật kiểm thử/hoàn thành/giao hàng | Có | Đơn mình phụ trách | Không | Không | Không | Không |
| Tạo/hủy đề nghị mua | Có | Không | Không | Không | Có | Không |
| Xác nhận nhận hàng và nhập mua | Có | Không | Có | Không | Không | Không |
| Phân quyền, nhật ký quản trị | Có | Không | Không | Không | Không | Không |

Kế toán giữ quyền xem sổ. Đăng ký công khai chỉ tạo Sale; Admin cấp các vai trò nghiệp vụ. Quyền được đọc lại từ database mỗi request.

## Sản phẩm và BOM

1. Tạo sản phẩm, mã linh kiện; thống nhất đơn vị cơ sở.
2. Thêm nhiều dòng linh kiện hoặc import Excel.
3. Lưu **draft**. Dòng trùng, mã không tồn tại hoặc định mức không dương bị từ chối.
4. Kích hoạt bản nháp: bản active trước chuyển **archived**; chỉ một bản active cho mỗi sản phẩm.
5. Bản active/archived không sửa trực tiếp; mở rồi lưu thành phiên bản nháp mới.

Import BOM tạo một định mức đầy đủ từ các dòng của sản phẩm trong file, không trộn với các dòng cũ ngoài file. Sau commit mở bản nháp đầu tiên để chỉnh sửa; các bản còn lại nằm trong lịch sử phiên bản. Import danh mục/BOM không thay đổi tồn kho.

## Đơn hàng

Đơn có nhiều `sales_order_items`. Mỗi dòng lưu `bom_id`, số lượng và đơn giá tại thời điểm tạo. `order_component_requirements.required` lưu tổng nhu cầu theo mã linh kiện, là căn cứ giữ và xuất kho. Thay đổi BOM mới không tính lại đơn cũ.

| Trạng thái trong code | Ý nghĩa nghiệp vụ |
| --- | --- |
| Form đang nhập | Sale kiểm tra vật tư trước khi lưu |
| `pending` | Đã lưu/chốt nhu cầu; đang chờ vật tư hoặc duyệt |
| `accepted` | Kho đã kiểm tra lại và giữ vật tư |
| `installing` | Đã xuất vật tư, bắt đầu sản xuất |
| `testing` | Thợ nhận phụ trách và kiểm thử |
| `completed` | Sản xuất hoàn thành |
| `delivering` | Kết thúc bước giao hàng của luồng hiện tại |
| `cancelled` | Hủy trước xuất vật tư, giải phóng giữ kho |

`material_status` tách riêng: `unknown`, `pending_material`, `pending_approval`, `reserved`, `issued`, `released`. Xanh/đỏ phản ánh kết quả kiểm tra; vàng là đơn chờ duyệt/bổ sung/xử lý. Chưa có BOM hợp lệ không được xác nhận đủ vật tư.

Kho duyệt qua `POST /orders/<id>/accept`. Trong cùng transaction, service đọc lại trạng thái và kiểm tra toàn bộ linh kiện. Chỉ thành công nếu giữ được tất cả. Duyệt lặp không giữ thêm.

Kho chuyển đơn sang `installing` qua `POST /orders/<id>/progress`: trừ cả tồn thực tế và đã giữ, tạo `stock_issues` và sổ xuất. Bước hoàn thành/giao hàng không trừ thêm. Thợ đầu tiên cập nhật bước sau sẽ trở thành `production_by`; các Thợ khác không cập nhật thay. `accepted_by` là người duyệt kho.

Hủy chỉ ở `pending` / `accepted`; không tăng tồn thực tế. Hủy lặp hoặc đơn đã xuất vật tư không được giải phóng lần nữa.

## Kho và mua hàng

```text
Khả dụng = stock − reserved − blocked
```

- Nhập thực tế, nhận đề nghị mua và kiểm kê đều ghi người thao tác.
- Không kiểm kê giảm tồn xuống dưới lượng đã giữ cộng bị khóa.
- Nhập hàng kiểm tra lại các đơn chờ theo snapshot, không tự giữ kho.
- Mua hàng tạo đề nghị từ phần thiếu hiện tại; một đơn chỉ có một đề nghị đang mở.
- Kho xác nhận nhận đủ theo đề nghị: nhập vật tư và đóng phiếu trong một transaction. Lặp lại không nhập thêm.
- `/accounting/` hiển thị vật tư thiếu, đề nghị mua và sổ kho. `/inventory/audit-history` dành cho Admin.

## Các endpoint chính

| Endpoint | Chức năng |
| --- | --- |
| `/inventory/` | Danh mục, tìm kiếm, BOM, import, phiên bản |
| `POST /inventory/bom` | Lưu/sửa nháp |
| `POST /inventory/boms/<id>/activate` | Kích hoạt BOM |
| `POST /inventory/imports/<components hoặc bom>/preview` | Xem trước Excel |
| `POST /inventory/imports/<loại>/<batch_id>/commit` | Xác nhận import |
| `POST /orders/check-stock` | Tổng hợp vật tư toàn đơn |
| `/orders/new` | Tạo đơn nhiều sản phẩm |
| `/orders/<id>` | Dòng sản phẩm, phiên bản BOM, nhu cầu và thiếu hụt |
| `POST /orders/<id>/accept` | Duyệt và giữ kho |
| `POST /orders/<id>/cancel` | Hủy và giải phóng |
| `POST /orders/<id>/purchase-request` | Đề nghị mua phần thiếu |
| `POST /orders/<id>/progress` | Xuất sản xuất / bước sản xuất tiếp theo |
| `POST /accounting/stock-entry` | Nhập kho thực tế |
| `POST /accounting/purchase-requests/<id>/receive` | Nhập đủ theo đề nghị mua |

## Chạy và kiểm tra

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

App khởi tạo schema/migration khi mở. Sao lưu database trước khi chạy phiên bản mới trên dữ liệu thật. Kiểm tra trước bằng `scripts/review_workflows.py`, script chỉ migrate bản sao.

Các lệnh hồi quy và phần dữ liệu cũ cần đối soát nằm trong [REVIEW-PA.md](REVIEW-PA.md). Hướng dẫn Turso/Vercel nằm trong [DEPLOY_VERCEL.md](DEPLOY_VERCEL.md).
