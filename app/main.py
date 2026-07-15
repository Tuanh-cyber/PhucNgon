"""
Application entry point.

Creates the FastAPI instance, registers routers, and configures
middleware (CORS, lifespan events, exception handlers).
"""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.routers import assessments, attempts, auth, plans, sessions, therapist, vocabulary

logger = logging.getLogger(__name__)

app = FastAPI(title="PhụcNgôn Backend", version="0.1.0")

# CORS: cho phép Frontend web (chạy trên trình duyệt) gọi API.
# allow_origins lấy từ settings.CORS_ORIGINS (đọc được từ .env) thay vì hardcode, để đổi khi
# deploy mà không cần sửa code. Trong DEV danh sách này gồm các cổng Expo Web thường dùng
# (8081 mặc định cho SDK mới, 19006 cho SDK cũ hơn). Khi deploy PRODUCTION, PHẢI thay bằng đúng
# domain thật của Frontend (vd https://phucngon.app), KHÔNG được để allow_origins=["*"] kèm
# allow_credentials=True vì đây là cấu hình KHÔNG AN TOÀN (trình duyệt sẽ từ chối tổ hợp này,
# và nếu chấp nhận thì cũng là lỗ hổng bảo mật nghiêm trọng).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(plans.router)
app.include_router(assessments.router)
app.include_router(attempts.router)
app.include_router(attempts.assignments_router)
app.include_router(vocabulary.router)
app.include_router(therapist.router)
app.include_router(sessions.router)


# ── Static files: ảnh từ vựng + audio câu hỏi/câu mẫu ────────────────────────
# Thư mục gốc đọc từ settings.STATIC_ASSETS_BASE_DIR (mặc định: <repo>/media — nằm trong
# repo để deploy cùng lên Render).
# Tên thư mục THẬT trên đĩa: Picture / Vocab / command_audio_wav / sentence_instance_wav.
# Thư mục thiếu -> LOG WARNING nhưng KHÔNG crash (vd audio vocab chưa có, môi trường CI
# không có file tĩnh) — request tới mount thiếu sẽ trả 404, frontend tự xử lý.
_STATIC_MOUNTS = [
    ("/static/pictures", "Picture"),
    ("/static/command-audio", "command_audio_wav"),
    ("/static/sentence-audio", "sentence_instance_wav"),
    ("/static/vocab-audio", "Vocab"),
    ("/static/sequence", "sequence"),  # Logic Sequence: ảnh level{N}/ + instruction_audio.wav
]
for _route, _dirname in _STATIC_MOUNTS:
    _dir = Path(settings.STATIC_ASSETS_BASE_DIR) / _dirname
    if _dir.is_dir():
        app.mount(_route, StaticFiles(directory=str(_dir)), name=_dirname)
    else:
        logger.warning(
            "Thư mục file tĩnh không tồn tại: %s — bỏ qua mount %s (ảnh/audio loại này "
            "sẽ 404). Kiểm tra STATIC_ASSETS_BASE_DIR trong .env nếu đây là môi trường thật.",
            _dir,
            _route,
        )


@app.get("/health", tags=["health"])
def health_check():
    """Kiểm tra service sống."""
    return {"status": "ok"}
