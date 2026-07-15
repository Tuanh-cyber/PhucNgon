"""
Color Recognition — dạng bài MỚI thứ 2: nghe audio hỏi màu -> chạm 1 trong 4 ô màu.

TÁI DÙNG Y NGUYÊN kiến trúc additive của logic_sequence: bảng riêng, exercise_type lưu
String, KHÔNG đụng bảng/enum/CHECK constraint bài nói. Chấm NHỊ PHÂN (đúng màu=100, sai=0)
ghi vào ExerciseSession/SessionResult như logic_sequence (GĐ2).

Ô MÀU VẼ TỪ HEX ở frontend (ảnh PNG nguồn là solid swatch — xác nhận bằng pixel check),
nên DB chỉ cần hex_code; image_file giữ lại để tham chiếu nguồn, KHÔNG serve.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Color(Base):
    """1 màu trong bảng màu (12 màu level 1)."""

    __tablename__ = "colors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    color_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)  # "COL001"
    name: Mapped[str] = mapped_column(String(50), nullable=False)   # "red"
    hex_code: Mapped[str] = mapped_column(String(9), nullable=False)  # "#F44336"
    image_file: Mapped[Optional[str]] = mapped_column(String(255))  # nguồn tham chiếu, KHÔNG serve


class ColorRecognitionExercise(Base):
    """1 bài nhận biết màu (CLR...) trỏ tới màu ĐÚNG."""

    __tablename__ = "color_recognition_exercises"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    exercise_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)  # "CLR001"
    exercise_type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'color_recognition'")
    )
    target_color_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("colors.id"), nullable=False
    )
    instruction_audio: Mapped[str] = mapped_column(String(255), nullable=False)  # "red.wav"
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    suitable_profiles: Mapped[Any] = mapped_column(JSONB, nullable=False)

    target_color: Mapped["Color"] = relationship()
