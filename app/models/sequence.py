"""
Logic Sequence — dạng bài MỚI: sắp xếp ảnh theo đúng trình tự hành động.

ADDITIVE hoàn toàn: 3 BẢNG RIÊNG, KHÔNG đụng bảng exercises/enum ExerciseType/CHECK
constraint của bài nói. Lý do tách bảng thay vì thêm vào `exercises`:
  - `exercises` có CHECK `ck_exercise_target_exclusivity` bắt buộc ĐÚNG 1 trong
    target_vocab_id/target_command_id/target_sentence_instance_id — logic_sequence
    KHÔNG có target nào trong số đó (nó trỏ sequence) -> thêm vào sẽ vỡ constraint.
  - exercise_type là ENUM DB (naming/command_identification/sentence_building) -> thêm
    "logic_sequence" phải ALTER TYPE (đụng schema cũ). Bảng riêng né được cả hai.

exercise_type lưu String (không tạo enum mới) — cùng cách therapy_sessions.mode.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Sequence(Base):
    """1 chuỗi hành động (vd 'Trồng cây' — 3 bước ảnh). Level 1/2/3 = 3/4/5 bước."""

    __tablename__ = "sequences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    sequence_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)  # "SQL1001"
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)  # 1..3
    step_count: Mapped[int] = mapped_column(Integer, nullable=False)

    steps: Mapped[list["SequenceStep"]] = relationship(
        back_populates="sequence",
        cascade="all, delete-orphan",
        order_by="SequenceStep.step_order",
    )


class SequenceStep(Base):
    """1 bước ảnh trong chuỗi. step_order = thứ tự ĐÚNG (dùng để chấm)."""

    __tablename__ = "sequence_steps"
    __table_args__ = (
        UniqueConstraint("sequence_id", "step_order", name="uq_sequence_step_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    sequence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sequences.id", ondelete="CASCADE"), nullable=False
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    image_file: Mapped[str] = mapped_column(String(255), nullable=False)

    sequence: Mapped["Sequence"] = relationship(back_populates="steps")


class LogicSequenceExercise(Base):
    """1 bài logic_sequence (SEQ...) trỏ tới 1 Sequence. Ngân hàng bài của dạng mới."""

    __tablename__ = "logic_sequence_exercises"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    exercise_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)  # "SEQ001"
    exercise_type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'logic_sequence'")
    )
    target_sequence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sequences.id"), nullable=False
    )
    suitable_profiles: Mapped[Any] = mapped_column(JSONB, nullable=False)  # ["wer","mixed"]

    target_sequence: Mapped["Sequence"] = relationship()
