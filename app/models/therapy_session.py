"""
TherapySession — PHIÊN tập theo rule.md mục 3: 1 phiên = 10 bài, bắt đầu bằng chọn
MODE + TOPIC, kết thúc khi đủ 10 bài hoặc bệnh nhân dừng sớm.

TẦNG MỚI BAO NGOÀI (additive): ExerciseSession (1 lượt làm 1 BÀI) giữ nguyên; mỗi bài
tùy chọn gắn vào 1 phiên qua exercise_sessions.therapy_session_id (nullable — luồng cũ
không có phiên vẫn hợp lệ y nguyên).

Ghi nhận đủ trường rule.md mục 3: profile (snapshot lúc tạo), mode, topic, vocab_level,
completed_count, total_retry_count, duration_seconds. Score/completion per-bài đã nằm ở
SessionResult; consecutive count đã nằm ở TopicProgress — không lặp lại.

mode/status lưu String + validate Literal ở tầng API (không tạo enum DB mới — additive
nhẹ nhất, không đụng chuỗi migration enum hiện có).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TherapySession(Base):
    __tablename__ = "therapy_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False
    )
    # naming | command_identification | sentence_building | mixed
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    # enum value topic; NULL = Mixed Topics (trộn mọi chủ đề)
    topic: Mapped[Optional[str]] = mapped_column(String(30))
    # vocab_level lúc BẮT ĐẦU phiên (từ TopicProgress của topic đó).
    # NULL khi Mixed Topics — level khi đó theo TỪNG BÀI (topic của bài nào lấy level topic đó).
    vocab_level: Mapped[Optional[int]] = mapped_column(Integer)
    # Snapshot profile lúc tạo phiên: broca_like | wernicke_like | mixed
    profile: Mapped[str] = mapped_column(String(20), nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    # in_progress | completed | stopped_early
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'in_progress'")
    )
    planned_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("10"))
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total_retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)
