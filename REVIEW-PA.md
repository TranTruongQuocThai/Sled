# Rà soát PA quản lý sản phẩm – linh kiện – kho – đơn hàng

Ngày rà soát: 31/10/2026.

Phạm vi là ứng dụng Flask đang chạy từ `app.py`, các controller, model, template và tài nguyên tĩnh. `legacy-ui/` là prototype riêng. PA đề xuất Laravel/MySQL; đợt sửa này giữ Flask + SQLite/Turso và đối chiếu theo quy tắc nghiệp vụ. Không chuyển framework hoặc triển khai lên production.

## Kết quả chính

Đã sửa các lệch nghiệp vụ trong mã nguồn. 46 kiểm thử Python và 21 kiểm thử JavaScript đạt. Bộ kiểm thử dùng database tạm. Migration được chạy lặp trên bản sao chỉ đọc của `warehouse.db`, giữ nguyên đơn hàng và các dòng nhu cầu vật tư đã có, không phát sinh lỗi khóa ngoại.

Chưa thể nghiệm thu trực quan bố cục: công cụ trình duyệt báo `The browser access host is unavailable` sau khi thử lại và khởi tạo lại. Kiểm thử DOM dùng HTML thật render từ Flask, xác minh hành vi JavaScript, không thay thế kiểm tra hình ảnh. Chưa chạy kiểm thử trên Turso/Vercel thật.

## Các điểm lệch đã sửa

| Vấn đề trước rà soát | Cách xử lý hiện tại | Mã nguồn chính |
| --- | --- | --- |
| Lưu/import BOM kích hoạt ngay, chưa có bước duyệt nháp | Lưu nháp; sửa nháp; kích hoạt riêng; bản cũ archived; chỉ một BOM active | `models/workflows.py`, `controllers/inventory.py` |
| Import BOM trộn với định mức cũ | Mỗi sản phẩm trong file tạo một BOM nháp đầy đủ; không giữ lại dòng cũ ngoài file | `models/excel_imports.py` |
| Đơn chỉ có một sản phẩm, chưa lưu phiên bản BOM theo dòng | `sales_order_items` lưu sản phẩm, số lượng, đơn giá và `bom_id`; nhu cầu được cộng gộp theo linh kiện | `models/workflows.py` |
| Kiểm tra trạng thái duyệt/hủy/tiến độ/nhận mua nằm ngoài transaction | Đọc và cập nhật trạng thái trong cùng `BEGIN IMMEDIATE`; thay đổi kho có điều kiện và kiểm tra số dòng | `models/workflows.py` |
| Có thể giữ/hủy/nhập mua lặp khi gửi đồng thời | Kiểm tra lại trạng thái sau khi lấy khóa; hủy không giải phóng vật tư của đơn khác; nhận mua chỉ nhập một lần | `models/workflows.py` |
| Xuất vật tư khi giao hàng | Kho xuất vật tư khi bắt đầu sản xuất; hoàn thành/giao hàng không trừ thêm | `models/workflows.py` |
| Thiếu số lượng bị khóa và lịch sử kiểm kê | Khả dụng = thực tế − đã giữ − bị khóa; nhập/xuất/giữ/giải phóng/điều chỉnh có người thao tác | `controllers/inventory.py`, `controllers/accounting.py` |
| Danh mục chưa đủ thao tác sửa/tìm/ngừng sử dụng | Bổ sung CRUD phù hợp, tìm mã/tên, metadata sản phẩm và hình ảnh qua URL; không xóa cứng | `controllers/inventory.py`, `templates/inventory.html` |
| Nhập kho chưa cập nhật trạng thái vật tư của đơn chờ | Kiểm tra lại các snapshot đơn chờ; chuyển đủ/thiếu, không tự giữ kho | `refresh_waiting_orders` |
| Kế toán gộp Kho/Mua hàng, Thợ có quyền duyệt giữ vật tư | Tách `warehouse` và `purchasing` theo lựa chọn của người dùng; Thợ xử lý sản xuất | `controllers/auth.py`, các decorator phân quyền |
| Quyền trong session có thể cũ; đăng ký tự chọn quyền nghiệp vụ | Đọc lại quyền từ database mỗi request; đăng ký mới chỉ được Sale; Admin cấp quyền nghiệp vụ | `controllers/auth.py` |
| Form thay đổi dữ liệu thiếu CSRF; forecast ghép HTML từ tên linh kiện | Thêm CSRF; dùng `textContent`; hủy request cũ và bỏ kết quả trả về lệch thứ tự | `models/security.py`, `static/app.js` |
| Import phụ thuộc quá nhiều lượt gọi database theo từng dòng | Tra cứu danh mục theo lô, insert nhiều dòng trong mỗi câu SQL; giao dịch kho cập nhật theo lô | `insert_rows`, `models/excel_imports.py` |
| Báo cáo Thợ dựa vào người duyệt kho, đơn hủy còn tính vào tổng giá trị | Tách `production_by` khỏi `accepted_by`; loại đơn hủy khỏi tổng giá trị báo cáo | `controllers/dashboard.py` |
| Database mới tạo sẵn giữ kho/trạng thái mẫu không nhất quán | Dữ liệu mẫu mới chưa giữ kho, có sổ tồn đầu và phiên bản BOM xác định | `models/repository.py` |
| Database Turso trống tự có tài khoản demo | Không seed demo trên Turso/Vercel; có CLI cấp Admin rõ ràng | `models/commands.py`, `app.py` |

## Đối chiếu 14 tiêu chí nghiệm thu

“Đạt tự động” mô tả mã nguồn và kiểm thử, không đồng nghĩa dữ liệu production đã được đối soát hoặc bố cục đã được kiểm tra bằng trình duyệt.

| # | Tiêu chí PA | Bằng chứng kiểm tra | Kết quả |
| --- | --- | --- | --- |
| 1 | Thêm, sửa, tìm sản phẩm/linh kiện | Tạo/sửa/tìm/ngừng sử dụng qua HTTP; giữ dữ liệu lịch sử | Đạt tự động |
| 2 | Một sản phẩm có nhiều dòng linh kiện | 150 dòng động trong DOM; BOM 500 linh kiện qua service | Đạt tự động |
| 3 | Thêm/xóa dòng không làm mất dòng khác | Xóa dòng giữa, giữ mã và số lượng của các dòng còn lại | Đạt tự động |
| 4 | Không trùng mã trong BOM | Validate và khóa chính `(bom_id, component_id)` | Đạt tự động |
| 5 | Import danh mục | Tiêu đề Việt/Anh; thêm mới/cập nhật rõ ràng; 1.000 dòng | Đạt tự động |
| 6 | Import BOM tạo các dòng giao diện | Commit mở bản nháp vừa tạo; HTML chứa đúng các dòng | Đạt tự động |
| 7 | Excel lỗi không ghi dữ liệu ngoài ý muốn | File hỏng/rỗng/trùng/sai định mức/tham chiếu đổi sau preview; rollback toàn bộ commit | Đạt tự động |
| 8 | Sale tạo đơn, tự tính vật tư | Nhiều sản phẩm, cộng gộp mã dùng chung, lưu snapshot | Đạt tự động |
| 9 | Xanh/đỏ/vàng, thiếu bao nhiêu | Kiểm tra thiếu/đủ/chưa xác định; badge chờ xử lý tách khỏi kiểm tra vật tư; DOM và template render | Đạt tự động; cần QA hình ảnh |
| 10 | Duyệt đồng thời không vượt tồn | Hai đơn tranh tồn; cùng một đơn duyệt hai lần; rollback khi một mã thiếu | Đạt tự động trên SQLite |
| 11 | Hủy giải phóng giữ kho | Không tăng tồn thực tế; hủy đồng thời không ảnh hưởng đơn khác | Đạt tự động |
| 12 | BOM mới không làm sai đơn cũ | Snapshot và `bom_id` không đổi sau kích hoạt BOM khác và migration lặp | Đạt tự động |
| 13 | Mọi nhập/xuất có lịch sử và người thao tác | Sổ nhập/xuất/giữ/giải phóng/điều chỉnh; nhận mua một lần | Đạt tự động |
| 14 | Phân quyền Admin/Kỹ thuật/Kho/Sale/Mua hàng | Ma trận endpoint, thu hồi quyền có hiệu lực request tiếp theo, chặn tự cấp quyền khi đăng ký | Đạt tự động |

## Dữ liệu hiện có cần đối soát

Kết quả từ `scripts/review_workflows.py` trên bản sao của database hiện có:

- 3 đơn hàng; thông tin đơn và snapshot cũ giữ nguyên sau migration lặp.
- 0 lỗi khóa ngoại; 0 dòng có tồn thực tế thấp hơn tổng đã giữ và bị khóa.
- 2 đơn còn trạng thái `confirmed` / `producing` của luồng cũ.
- 3 dòng đơn chưa có căn cứ xác định phiên bản BOM gốc. Migration không tự gán BOM hiện tại thành phiên bản lịch sử.
- 5 mã có số dư `reserved` chưa khớp sổ giữ vật tư theo đơn.

Không tự sửa các số dư hoặc suy đoán phiên bản BOM cũ. Cần đối chiếu chứng từ/đơn gốc để quyết định đơn nào đang giữ vật tư, đơn nào đã xuất và số dư đúng. Service chặn việc hủy/xuất khi sổ giữ của đơn không khớp nhu cầu. Các trạng thái đơn cũ không tự chuyển sang luồng mới.

Chưa chạy ứng dụng mới lên database gốc; các lệnh kiểm thử và rà soát chỉ dùng database tạm/bản sao.

## Quy ước và giới hạn triển khai

- MVP dùng một kho vật lý. Nhiều kho/điều chuyển/lệnh sản xuất là phần mở rộng được nêu ở cuối PA.
- Luồng web thay cho các tên API Laravel đề xuất. Tên trạng thái được ánh xạ trong `WORKFLOW.md`.
- Hỗ trợ `.xlsx`, tối đa 10.000 dòng dữ liệu, 32 cột, request upload 8 MB; không hỗ trợ `.xls` nhị phân cũ.
- Linh kiện dùng một đơn vị cơ sở; số lượng có tối đa 6 chữ số thập phân. Số lượng sản phẩm trong đơn là số nguyên dương.
- Hủy đơn chỉ trước khi xuất vật tư sản xuất. Hàng đã xuất cần nghiệp vụ hoàn trả/đảo xuất riêng, không tự cộng kho bằng thao tác hủy.
- Danh sách thiếu hiển thị đơn cũ trước. Kho chủ động duyệt theo ưu tiên; hệ thống kiểm tra lại mỗi lần duyệt.
- Hình ảnh sản phẩm được quản lý bằng URL HTTP(S), chưa có kho lưu file ảnh riêng.
- Kiểm thử số lượt SQL xác nhận xử lý theo lô; chưa đo thời gian thực tế trên Turso/Vercel.

## Lệnh kiểm tra lại

### Cập nhật giao diện

- Đồng bộ bố cục tổng quan, danh mục, BOM, đơn hàng, kho/mua hàng, báo cáo, nhân sự, nhật ký và đăng nhập/đăng ký bằng `static/workflows.css`.
- Dùng thẻ tóm tắt mở popup; chi tiết chia tab, danh sách có tìm kiếm không dấu, bộ lọc và phân trang. Form tạo đơn giữ bố cục riêng để thuận tiện nhập nhiều sản phẩm và kiểm tra vật tư.
- Popup hỗ trợ Escape, khôi phục focus, tab bằng bàn phím, xác nhận thao tác và chặn gửi lặp. Chi tiết đơn tải theo yêu cầu, bỏ qua phản hồi cũ khi đóng popup.
- Xem trước Excel hiển thị từng cột, lọc dòng lỗi, không cho xác nhận khi có lỗi. BOM thay đổi chưa lưu không được kích hoạt từ nút của bản đã lưu.
- Gỡ hướng dẫn tài khoản mẫu và giá trị đăng nhập điền sẵn; giữ nguyên tài khoản và dữ liệu hiện có.
- Kiểm thử DOM trên HTML render thật theo 6 vai trò; đã kiểm tra HTTP các trang chính và đơn có sẵn trên server local. Chưa kiểm tra ảnh chụp bố cục vì trình duyệt tự động chưa kết nối được.

### Thực hiện kiểm thử

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B scripts/review_workflows.py
npm.cmd install --prefix .venv/frontend-tests --no-audit --no-fund jsdom@29.1.1
.\.venv\Scripts\python.exe -B scripts/render_test_views.py
node --test tests/test_ui.cjs
node --check static/app.js
git diff --check
```

Đã kiểm tra với Python 3.11 và Node 24. Test Python không cần dịch vụ ngoài. DOM test dùng `jsdom` trong `.venv/frontend-tests`, không thêm dependency Node vào ứng dụng production.
