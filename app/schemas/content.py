"""
Pydantic schemas cho danh sách bài + nội dung chi tiết 1 bài (render UI).

QUY TẮC BẢO MẬT NỘI DUNG: các schema *Content KHÔNG BAO GIỜ chứa đáp án đúng
(canonical_word / accepted_answers / full_sentence / đánh dấu choice đúng) — đáp án chỉ
tồn tại phía scoring khi chấm bài.
"""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel


# ── Danh sách bài theo loại (GET /plans/me/assignments) ──────────────────────
class AssignmentListItem(BaseModel):
    """1 bài trong danh sách bài của patient theo loại (+topic cho luồng chọn bài mới)."""

    assignment_id: str
    exercise_id: str
    exercise_type: str
    topic: str                # enum value của Exercise.topic, vd "food_drink"
    order_index: int
    status: Literal["pending", "completed"]


# ── Từ vựng cho flashcard (GET /vocabulary) ──────────────────────────────────
class VocabularyItem(BaseModel):
    """1 từ vựng kèm URL ảnh + audio để làm flashcard. KHÔNG chứa accepted_answers."""

    vocab_id: str
    word: str                       # canonical_word
    topic: str                      # enum value, vd "food_drink"
    word_type: str                  # enum value: noun | verb | adjective
    image_url: Optional[str]        # /static/pictures/...; None nếu thiếu file
    audio_url: Optional[str]        # /static/vocab-audio/...; None nếu thiếu file


# ── Bài tập đề xuất theo profile bệnh (GET /patients/me/recommended-exercises) ─
class RecommendedExercise(BaseModel):
    """1 loại bài kèm trọng số gợi ý theo profile bệnh (rule.md Profile => Exercise Weight)."""

    exercise_type: str
    display_name: str
    weight: float
    recommended: bool  # weight >= 0.3 -> đề xuất mạnh cho profile này


# ── Nội dung chi tiết 1 bài (GET /assignments/{id}/content) ──────────────────
class NamingContent(BaseModel):
    """Bài Gọi tên: nhìn ảnh, nói tên. KHÔNG trả canonical_word/accepted_answers."""

    exercise_type: Literal["naming"] = "naming"
    image_url: Optional[str]  # None nếu thiếu ảnh -> frontend hiện placeholder
    prompt: str = "Tên của vật này là gì?"
    # Audio phát âm mẫu của từ (/static/vocab-audio/{audio_file}); None nếu thiếu file.
    vocab_audio_url: Optional[str] = None


class RecognitionChoice(BaseModel):
    """1 lựa chọn trong bài Nghe và đoán (recognition) — KHÔNG đánh dấu đúng/sai."""

    vocab_id: str
    image_url: Optional[str]
    word: str


class CommandRecognitionContent(BaseModel):
    """Bài Nghe và đoán, mode recognition: nghe câu hỏi, chạm chọn 1 trong 4 ô."""

    exercise_type: Literal["command_identification"] = "command_identification"
    mode: Literal["recognition"] = "recognition"
    command_audio_url: Optional[str]
    command_text: str  # caption/accessibility — là CÂU HỎI mô tả, không phải đáp án
    choices: list[RecognitionChoice]  # 4 phần tử, đã trộn ngẫu nhiên (seed ổn định)


class CommandRepetitionContent(BaseModel):
    """Bài Nghe và đoán, mode repetition: nghe câu hỏi + nhìn ảnh, nói to từ đó."""

    exercise_type: Literal["command_identification"] = "command_identification"
    mode: Literal["repetition"] = "repetition"
    command_audio_url: Optional[str]
    # Theo Exercise_spec.md Mode 2: ảnh target hiện TRONG LÚC phát audio (không kèm chữ).
    image_url: Optional[str]
    prompt: str = "Nghe và nhắc lại"


class SentenceBuildingContent(BaseModel):
    """Bài Hoàn thành câu: nhìn template + ảnh gợi ý, nói cả câu. KHÔNG trả full_sentence."""

    exercise_type: Literal["sentence_building"] = "sentence_building"
    template_display: str  # vd "Tôi muốn ăn ____"
    image_url: Optional[str]  # ảnh gợi ý từ cần điền
    sentence_audio_url: Optional[str]  # audio câu mẫu (chỉ dùng khi sai -> nghe và nhắc lại)
    prompt: str = "Hoàn thành câu"


# Union trả về từ endpoint — FastAPI serialize đúng model con theo exercise_type/mode.
AssignmentContent = Union[
    NamingContent,
    CommandRecognitionContent,
    CommandRepetitionContent,
    SentenceBuildingContent,
]
