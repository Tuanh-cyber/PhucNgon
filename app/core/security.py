"""
Bảo mật: băm mật khẩu (passlib/bcrypt) + tạo/giải mã JWT (python-jose).

- hash_password / verify_password: băm mật khẩu MỘT CHIỀU — KHÔNG thể giải mã ngược
  lại thành mật khẩu gốc, chỉ so sánh được đúng/sai.
- create_access_token / decode_access_token: JWT ký bằng SECRET_KEY đọc từ settings
  (KHÔNG hardcode secret trong code).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# bcrypt qua passlib. deprecated="auto" để tự nâng cấp hash cũ nếu sau này đổi scheme.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


# ── Password hashing ──────────────────────────────────────────────────────────

def hash_password(plain_password: str) -> str:
    """Băm mật khẩu (một chiều). Trả về chuỗi hash để lưu vào DB."""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """So khớp mật khẩu người dùng nhập với hash đã lưu. True nếu đúng."""
    return _pwd_context.verify(plain_password, hashed_password)


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(
    user_id: str,
    role: str,
    expires_minutes: Optional[int] = None,
) -> str:
    """
    Tạo JWT access token chứa user_id (sub) + role, có hạn dùng.

    Hạn dùng mặc định lấy từ settings.ACCESS_TOKEN_EXPIRE_MINUTES (mặc định 90 ngày,
    override được từ .env). Truyền expires_minutes để ghi đè cho từng trường hợp riêng.

    Payload:
      sub  : str(user_id)
      role : role của user ("patient" | "therapist" | ...)
      exp  : thời điểm hết hạn (UTC)
    """
    if expires_minutes is None:
        expires_minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "exp": now + timedelta(minutes=expires_minutes),
        "iat": now,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """
    Giải mã + xác thực JWT. Trả về payload (dict) nếu hợp lệ, None nếu token
    sai chữ ký hoặc đã hết hạn.
    """
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
