"""Application settings loaded from environment variables via pydantic-settings."""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+psycopg://ngotuananh@localhost:5432/phucngon_dev"
    SECRET_KEY: str = "change-me-in-production-use-a-long-random-string"
    # Hạn dùng JWT access token, TÍNH BẰNG PHÚT. Mặc định 129600 phút = 90 ngày.
    # 90 ngày — vì app cho người lớn tuổi, ưu tiên ít phải đăng nhập lại ("vào app là vào
    # luôn"). Override được từ .env nếu môi trường cần khác. Nếu cần bảo mật cao hơn
    # (refresh token), cân nhắc lại thiết kế này sau; hiện tại chọn đơn giản theo đúng yêu
    # cầu UX.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 129600
    APP_ENV: str = "development"
    # Danh sách origin được phép gọi API qua trình duyệt (CORS). Đọc được từ .env (định dạng
    # JSON, vd: CORS_ORIGINS='["https://phucngon.app"]') để đổi khi deploy mà KHÔNG phải sửa
    # code. Default dưới đây liệt kê các cổng Expo Web thường dùng trong môi trường DEV:
    #   - 8081  : cổng mặc định của Expo SDK mới
    #   - 19006 : cổng của Expo SDK cũ hơn
    #   - 3000  : dev server web khác (nếu có)
    # Khi lên PRODUCTION, PHẢI thay bằng đúng domain thật của Frontend (vd https://phucngon.app)
    # và TUYỆT ĐỐI KHÔNG để ["*"] kèm allow_credentials=True — đây là tổ hợp KHÔNG AN TOÀN
    # (trình duyệt sẽ từ chối, và nếu chấp nhận thì cũng là lỗ hổng bảo mật nghiêm trọng).
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:8081",
        "http://127.0.0.1:8081",
        "http://localhost:19006",
        "http://127.0.0.1:19006",
    ]

    # Thư mục GỐC chứa các thư mục file tĩnh (ảnh/audio bài tập) — mặc định là thư mục CHA
    # của repo (nơi có sẵn Picture/, command_audio_wav/, sentence_instance_wav/ cùng cấp với
    # phucngon-backend). Override từ .env khi deploy (vd trỏ tới volume mount).
    # LƯU Ý tên thư mục thật trên đĩa: "Picture" (P hoa), "sentence_instance_wav" (KHÔNG phải
    # sentence_audio_wav) — main.py mount đúng các tên này.
    STATIC_ASSETS_BASE_DIR: str = str(Path(__file__).resolve().parents[3])

    # ASR (Module 2 - Vy). "fake" hoặc "real". Mặc định "fake" cho tới khi Vy finetune xong.
    ASR_MODE: str = "fake"
    ASR_SERVICE_URL: str = "http://localhost:8001"  # chỉ dùng khi ASR_MODE="real". Endpoint = {URL}/transcribe

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        if not v.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL phải dùng driver postgresql+psycopg:// (psycopg v3)")
        return v


settings = Settings()
