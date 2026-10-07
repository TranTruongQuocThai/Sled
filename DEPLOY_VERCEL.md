# Deploy SLED lên Vercel

## Trạng thái hiện tại

Project đã sẵn sàng để Vercel nhận diện Flask từ `app.py`. Khi có biến `DATABASE_URL`, ứng dụng tự kết nối PostgreSQL bằng `psycopg`. SQLite chỉ là chế độ local/demo.

## Deploy demo

1. Push source lên GitHub.
2. Truy cập `https://vercel.com/new` và import repository `TranTruongQuocThai/Sled`.
3. Giữ nguyên Framework Preset tự nhận diện Flask; không đặt Build Command hoặc Output Directory.
4. Tạo PostgreSQL cloud (Vercel Postgres, Neon hoặc Supabase) và lấy connection string dạng `postgresql://...`.
5. Trong **Settings → Environment Variables**, thêm:

   ```text
   SECRET_KEY=<một chuỗi ngẫu nhiên dài ít nhất 32 ký tự>
   DATABASE_URL=postgresql://<user>:<password>@<host>/<database>?sslmode=require
   ```

6. Nhấn **Deploy**. Schema và các tài khoản mẫu sẽ được tạo tự động ở lần khởi động đầu tiên.

## Deploy bằng Vercel CLI

```bash
npm install -g vercel
vercel
vercel --prod
```

## Production

Không cần đưa `warehouse.db` lên Vercel. Khi `DATABASE_URL` đã có, đơn hàng, tồn kho, tài khoản và sổ kế toán sẽ lưu ổn định trong PostgreSQL giữa các lần deploy.
