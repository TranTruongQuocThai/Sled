# Deploy SLED lên Vercel

Ứng dụng Flask dùng Turso trên Vercel. Local dùng SQLite `warehouse.db` nếu không cấu hình Turso. Không commit `.env` hoặc token.

## Cấu hình

Ba biến production bắt buộc:

- `TURSO_DATABASE_URL`: URL database `libsql://...`.
- `TURSO_AUTH_TOKEN`: token của database.
- `SECRET_KEY`: secret riêng cho cookie đăng nhập.

File tĩnh được CDN phục vụ từ `public/static` tại `/static/...`. Nội dung phải khớp `static/`, gồm `app.js` và `workflows.css`.

## Database và tài khoản

Schema/migration được khởi tạo khi app mở. Sao lưu database trước khi đưa mã mới vào vận hành. Kết quả kiểm tra trên bản sao SQLite và các số dư cần đối soát nằm trong [REVIEW-PA.md](REVIEW-PA.md).

Database Turso mới không tự có tài khoản demo. Trong môi trường quản trị đã cấu hình đúng database, tạo tài khoản Admin bằng:

```powershell
.\.venv\Scripts\python.exe -m flask --app app create-admin --name "Quản trị" --email "admin@doanhnghiep.vn"
```

CLI hỏi và xác nhận mật khẩu, tối thiểu 12 ký tự; không ghi đè tài khoản/email đã có. Chạy lệnh này chỉ cho database mà bạn muốn cấp Admin. Sau đó Admin cấp vai trò Kho và Mua hàng cho tài khoản nhân viên.

## Đưa bản mới lên

```powershell
npx vercel login
npx vercel link
npx vercel env add TURSO_DATABASE_URL production
npx vercel env add TURSO_AUTH_TOKEN production
npx vercel env add SECRET_KEY production
npx vercel deploy --prod
```

Các lệnh này là hướng dẫn, chưa được chạy trong đợt rà soát.

Trước nghiệm thu production, kiểm tra trực quan giao diện và chạy thử trên Turso: duyệt cạnh tranh tồn, hủy lặp, nhận mua lặp, import nhiều dòng. Hiện các ca hồi quy đã chạy trên SQLite/DOM; chưa có kết quả kiểm thử Turso/Vercel thật.
