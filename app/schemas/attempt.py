"""
Pydantic schemas cho attempt (làm bài) — hình dạng JSON request/response.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class ExerciseInfoResponse(BaseModel):
    """
    Thông tin CƠ BẢN của 1 bài tập trả cho Frontend TRƯỚC khi làm bài.

    CỐ Ý không chứa canonical_word / accepted_answers / full_sentence... — tức KHÔNG
    lộ đáp án đúng ra JSON, tránh Frontend vô tình hiển thị đáp án cho bệnh nhân thấy
    trước khi làm bài.
    """

    exercise_id: str
    exercise_type: str
    topic: str
    vocab_level: int
    mode: Optional[str] = None


class FeedbackItem(BaseModel):
    """1 câu nhận xét có phân loại cho màn Kết quả bài tập.

    type: "ok" (điều làm đúng, tô xanh) | "warn" (cần cải thiện / lỗi input, tô vàng/đỏ).
    CHỈ là text hiển thị — KHÔNG ảnh hưởng điểm.
    """

    type: str
    text: str


class AttemptSubmitResponse(BaseModel):
    """
    Response khi NỘP BÀI thật (POST /assignments/{id}/submit) — đã lưu DB.

    Field bám sát UI kết quả bài tập (Ảnh 3):
      - score            -> điểm tổng "85/100"
      - accuracy_score / completion_score / fluency_score -> 3 tiêu chí RIÊNG lượt này
        (cùng công thức attempt_to_metrics với /patients/me/stats — single source).
      - result           -> pass/near/retry/correct/incorrect/skip/invalid
      - feedback          -> list {type, text} có phân loại (ok/warn) cho UI
      - feedback_messages -> list[str] rút gọn (giữ tương thích client cũ; = feedback[].text)
      - transcript       -> nội dung bệnh nhân đã nói (đã chuẩn hoá)
      - is_final         -> true nếu session đã graded (không cho thử lại nữa),
                            false nếu còn được retry (near/retry/invalid)
    """

    score: Optional[float]
    # 3 tiêu chí cho RIÊNG lượt vừa làm (None = lượt này không tính được tiêu chí đó,
    # vd bài touch không có accuracy/fluency; input invalid không có accuracy/fluency).
    accuracy_score: Optional[float] = None
    completion_score: Optional[float] = None
    fluency_score: Optional[float] = None
    result: str
    feedback: list[FeedbackItem] = []
    feedback_messages: list[str]
    transcript: Optional[str]
    attempt_number: int
    is_final: bool
    # Progression theo topic (rule.md): leveled_up=True khi lượt bài này vừa làm bệnh nhân
    # đạt 3 lần liên tiếp score>=80 cùng topic -> vocab level tăng, new_level là level mới.
    # Frontend hiện "Chúc mừng! Bạn đã lên Level {new_level}".
    leveled_up: bool = False
    new_level: Optional[int] = None


class AttemptResponse(BaseModel):
    """
    Hình dạng response cho 1 lượt chấm điểm, map 1-1 từ dataclass ScoreResult.

    Hình dạng response này PHẢI khớp chính xác với dataclass ScoreResult trong
    scoring_service.py — nếu Nam đổi field bên đó, phải đổi theo ở đây.

    from_attributes=True (Pydantic v2) cho phép convert trực tiếp từ dataclass
    ScoreResult sang JSON mà không cần map tay từng field.
    """

    model_config = ConfigDict(from_attributes=True)

    exercise_id: str
    exercise_type: str
    mode: Optional[str]
    vocab_level: int
    topic: str
    score: Optional[float]
    raw_score: Optional[float]
    weighted_score: Optional[float]
    is_correct: Optional[bool]
    components: dict[str, Any]
    result: str
    attempt_number: int
    used_fallback_audio: bool
    transcript: Optional[str]
    selected_vocab_id: Optional[str]
    audio_duration_s: Optional[float]
    asr_confidence: Optional[float]
