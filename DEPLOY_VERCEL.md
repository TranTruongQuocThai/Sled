# Deploy SLED lên Vercel

## Trạng thái hiện tại

Project đã sẵn sàng để Vercel nhận diện Flask từ `app.py`. Bản deploy demo tạo SQLite trong `/tmp/sled-warehouse.db` để ứng dụng có thể khởi tạo và chạy.

> Dữ liệu SQLite trong `/tmp` không bền vững trên Vercel: có thể biến mất khi function khởi động lại, scale sang instance khác hoặc deploy phiên bản mới. Không sử dụng cấu hình này cho dữ liệu vận hành thật.

## Deploy demo

1. Push source lên GitHub.
2. Truy cập `https://vercel.com/new` và import repository `TranTruongQuocThai/Sled`.
3. Giữ nguyên Framework Preset tự nhận diện Flask; không đặt Build Command hoặc Output Directory.
4. Trong **Settings → Environment Variables**, thêm:

   ```text
   SECRET_KEY=<một chuỗi ngẫu nhiên dài ít nhất 32 ký tự>
   ```

5. Nhấn **Deploy**.

## Deploy bằng Vercel CLI

```bash
npm install -g vercel
vercel
vercel --prod
```

## Production

Trước khi đưa hệ thống kho vào vận hành, cần chuyển `models/repository.py` từ SQLite sang PostgreSQL cloud (Vercel Postgres, Neon hoặc Supabase) và lưu chuỗi kết nối trong `DATABASE_URL`. Khi đó đơn hàng, tồn kho, tài khoản và sổ kế toán sẽ tồn tại ổn định giữa các lần deploy.
