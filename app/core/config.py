"""Application settings loaded from environment variables via pydantic-settings."""

import json
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # DATABASE_URL: Đọc từ env, default = Docker local Postgres.
    # QUAN TRỌNG: Render trả "postgres://" (legacy), nhưng SQLAlchemy2 cần "postgresql://".
    # Xử lý tự động bên dưới ở @field_validator.
    DATABASE_URL: str = "postgresql+psycopg://ngotuananh@localhost:5432/phucngon_dev"

    # SECRET_KEY: JWT signing key. Đọc từ env, DEFAULT = dev value.
    # ⚠️ PRODUCTION PHẢI SET BỘ KHÁC MẠNH (32+ ký tự ngẫu nhiên).
    # Ví dụ: openssl rand -hex 32
    SECRET_KEY: str = "change-me-in-production-use-a-long-random-string"

    # Hạn dùng JWT access token, TÍNH BẰNG PHÚT. Mặc định 129600 phút = 90 ngày.
    # 90 ngày — vì app cho người lớn tuổi, ưu tiên ít phải đăng nhập lại ("vào app là vào
    # luôn"). Override được từ .env nếu môi trường cần khác. Nếu cần bảo mật cao hơn
    # (refresh token), cân nhắc lại thiết kế này sau; hiện tại chọn đơn giản theo đúng yêu
    # cầu UX.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 129600

    APP_ENV: str = "development"

    # CORS_ORIGINS: Danh sách origin được phép gọi API qua trình duyệt.
    # Đọc từ env (định dạng JSON cách bằng phẩy hoặc JSON array): vd CORS_ORIGINS="https://phucngon.app,https://app.phucngon.app"
    # Default dưới đây liệt kê các cổng Expo Web thường dùng trong môi trường DEV.
    # Khi lên PRODUCTION, PHẢI thay bằng đúng domain thật của Frontend (vd https://phucngon.app)
    # và TUYỆT ĐỐI KHÔNG để ["*"] kèm allow_credentials=True — đây là tổ hợp KHÔNG AN TOÀN.
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:8081",
        "http://127.0.0.1:8081",
        "http://localhost:19006",
        "http://127.0.0.1:19006",
    ]

    # STATIC_ASSETS_BASE_DIR: Thư mục GỐC chứa Picture/, command_audio_wav/, sentence_instance_wav/.
    # Default = thư mục cha của repo. Override từ .env khi deploy (vd volume mount Render).
    STATIC_ASSETS_BASE_DIR: str = str(Path(__file__).resolve().parents[3])

    # ASR (Module 2 - Vy). "fake" hoặc "real". Mặc định "fake" cho tới khi Vy finetune xong.
    # Deploy prod: set ASR_MODE="real" + ASR_SERVICE_URL="https://anh-ngotuananh29--phucngon-asr-asrservice-web.modal.run"
    ASR_MODE: str = "fake"
    ASR_SERVICE_URL: str = "http://localhost:8001"  # Endpoint = {URL}/transcribe

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_db_url(cls, v: str) -> str:
        """Đổi tiền tố 'postgres://' (Render) thành 'postgresql://' (SQLAlchemy2) tự động."""
        if isinstance(v, str):
            # Render: postgres://... → postgresql+psycopg://...
            if v.startswith("postgres://"):
                v = "postgresql+psycopg://" + v[len("postgres://"):]
            # Nếu chưa có driver: postgresql://... → postgresql+psycopg://...
            elif v.startswith("postgresql://"):
                v = "postgresql+psycopg://" + v[len("postgresql://"):]
        return v

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        """Kiểm tra DATABASE_URL đã đúng format."""
        if not v.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL phải dùng driver postgresql+psycopg:// (psycopg v3)")
        return v

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v) -> list[str]:
        """
        Parse CORS_ORIGINS từ env.
        - Nếu là JSON array string: '["https://a.com", "https://b.com"]' → parse
        - Nếu là dấu phẩy: 'https://a.com,https://b.com' → split
        - Nếu là list: keep as-is (default)
        """
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):  # JSON array
                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                    raise ValueError(f"CORS_ORIGINS JSON invalid: {v}")
            else:  # Comma-separated
                return [x.strip() for x in v.split(",") if x.strip()]
        return v


settings = Settings()
