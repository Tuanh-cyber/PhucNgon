"""
Pydantic schemas cho dạng bài COLOR RECOGNITION (nghe audio hỏi màu -> chạm ô màu).

Ô màu VẼ TỪ HEX ở frontend — content trả hex_code + name, KHÔNG có ảnh.
Màu ĐÚNG không được đánh dấu trong options; correct_color_id chỉ trả SAU khi nộp.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class ColorOption(BaseModel):
    """1 ô màu trong 4 lựa chọn — KHÔNG đánh dấu đúng/sai."""

    color_id: str   # mã ổn định "COL001" (dùng làm selected_color_id khi nộp)
    name: str       # "red"
    hex_code: str   # "#F44336" — FE vẽ ô bằng backgroundColor


class ColorRecognitionContent(BaseModel):
    """GET /color-recognition/{exercise_code} — nội dung render màn chọn màu."""

    exercise_code: str
    exercise_type: Literal["color_recognition"] = "color_recognition"
    level: int
    instruction_audio_url: Optional[str]   # /static/color-audio/{file}
    # Caption đề bài dạng chữ (accessibility — đọc kèm audio), vd "red".
    # Lưu ý: options cũng hiện name nên caption này đồng nghĩa gợi ý mạnh —
    # cùng pattern command_text của CMD recognition (đã chấp nhận từ trước).
    question_color_name: str
    options: list[ColorOption]             # 4 ô: 1 đúng + 3 nhiễu, XÁO ở server


class ColorRecognitionSubmitRequest(BaseModel):
    """POST /color-recognition/{exercise_code}/submit."""

    selected_color_id: str                     # "COL003"
    therapy_session_id: Optional[str] = None   # gắn vào phiên (optional)


class ColorRecognitionSubmitResponse(BaseModel):
    """Chấm NHỊ PHÂN: đúng màu -> 100/correct; sai -> 0/retry (cho làm lại)."""

    score: float                          # 100 | 0
    result: Literal["correct", "retry"]
    completed: bool                       # = đúng màu
    is_correct: bool
    attempt_number: int
    correct_color_id: str                 # CHỈ lộ SAU khi nộp (FE tô xanh ô đúng)
