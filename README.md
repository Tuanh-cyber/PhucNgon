# PhụcNgôn Backend

PhụcNgôn là ứng dụng hỗ trợ phục hồi ngôn ngữ cho bệnh nhân sau đột quỵ.
Backend được xây dựng bằng **FastAPI**, **SQLAlchemy 2.0 (async)**, **PostgreSQL** (psycopg v3),
**Alembic** để quản lý migration và **Pydantic v2** để validate dữ liệu.

## Chạy local

```bash
# 1. Tạo và kích hoạt môi trường ảo
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. Cài dependencies
pip install -r requirements.txt

# 3. Cấu hình biến môi trường
cp .env.example .env
# Điền DATABASE_URL và các biến cần thiết vào .env

# 4. Chạy migration
alembic upgrade head

# 5. Khởi động server
uvicorn app.main:app --reload
```

<!-- Hướng dẫn chi tiết sẽ được bổ sung sau -->
