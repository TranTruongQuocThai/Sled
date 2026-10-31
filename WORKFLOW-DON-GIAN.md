# SLED làm việc thế nào?

1. **Kỹ thuật** khai báo sản phẩm và định mức nhiều linh kiện. Có thể nhập Excel. BOM được lưu nháp, kiểm tra rồi mới kích hoạt.
2. **Sale** chọn một hoặc nhiều sản phẩm, nhập số lượng. Hệ thống cộng nhu cầu vật tư, hiển thị đủ/thiếu. Sale vẫn lưu được đơn thiếu vật tư; bước này chưa giữ kho.
3. **Mua hàng** tạo đề nghị cho các mã còn thiếu. **Kho** nhập hàng thực tế; hệ thống kiểm tra lại đơn chờ, chưa tự giữ vật tư.
4. **Kho** duyệt đơn: kiểm tra lại và giữ đủ tất cả linh kiện. Khi bắt đầu sản xuất, Kho xuất vật tư một lần.
5. **Thợ** nhận phụ trách sản xuất, cập nhật kiểm thử → hoàn thành → giao hàng.
6. **Admin** phân quyền và xem nhật ký. **Kế toán** xem sổ và số liệu.

Xanh: đủ vật tư tại thời điểm kiểm tra. Đỏ: thiếu vật tư, có số lượng thiếu từng mã. Vàng: chờ duyệt/bổ sung/xử lý. Chưa có BOM hợp lệ thì chưa được xác nhận đủ.

Hủy đơn trước xuất sản xuất sẽ giải phóng lượng đã giữ, không cộng tồn thực tế. BOM mới không làm thay đổi vật tư của đơn đã chốt.

Chi tiết: [WORKFLOW.md](WORKFLOW.md). Kết quả rà soát và dữ liệu cũ cần đối soát: [REVIEW-PA.md](REVIEW-PA.md).
