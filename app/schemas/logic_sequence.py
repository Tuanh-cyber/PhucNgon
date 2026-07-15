"""
Pydantic schemas cho dạng bài LOGIC SEQUENCE (sắp xếp ảnh theo trình tự).

BẢO MẬT NỘI DUNG: content KHÔNG BAO GIỜ chứa step_order đúng — thứ tự đúng chỉ trả
SAU KHI nộp (correct_order) để FE hiện đáp án.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class SequenceStepItem(BaseModel):
    """1 bước ảnh ĐÃ XÁO — chỉ có id + ảnh, KHÔNG lộ vị trí đúng."""

    step_id: str
    image_url: Optional[str]  # /static/sequence/level{n}/...; None nếu thiếu file


class LogicSequenceContent(BaseModel):
    """GET /logic-sequence/{exercise_id} — nội dung render màn sắp xếp."""

    exercise_id: str
    exercise_type: Literal["logic_sequence"] = "logic_sequence"
    title: str
    level: int
    step_count: int
    instruction_audio_url: Optional[str]
    steps: list[SequenceStepItem]  # ĐÃ XÁO ở server (mỗi lần gọi xáo lại)


class LogicSequenceSubmitRequest(BaseModel):
    """POST /logic-sequence/{exercise_id}/submit."""

    ordered_step_ids: list[str]           # thứ tự bệnh nhân xếp
    therapy_session_id: Optional[str] = None  # gắn vào phiên (optional, như bài nói)


class StepFeedback(BaseModel):
    """Đánh dấu từng vị trí bệnh nhân đặt — FE tô xanh/đỏ (không ảnh hưởng score)."""

    step_id: str
    position: int          # vị trí bệnh nhân đặt (1-based)
    correct: bool          # bước này có nằm ĐÚNG VỊ TRÍ TUYỆT ĐỐI không


class LogicSequenceSubmitResponse(BaseModel):
    """Kết quả chấm NHỊ PHÂN: khớp hoàn toàn -> 100; sai >=1 vị trí -> 0."""

    score: float                       # 100 | 0
    result: Literal["correct", "retry"]  # 100 -> correct (final); 0 -> retry (làm lại được)
    completed: bool                    # = result == "correct" (rule >50 -> pass)
    attempt_number: int
    step_feedback: list[StepFeedback]
    correct_order: list[str]           # thứ tự ĐÚNG (chỉ trả SAU khi nộp)
