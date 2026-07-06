"""Assessment and AssessmentResult models.

AssessmentResult is a 1-1 composition of Assessment (ON DELETE CASCADE).
Its 3 score fields (accuracy_score, completion_score, fluency_score) là số liệu
DO BÁC SĨ HOẶC NGƯỜI NHÀ NHẬP TAY lúc đăng ký (khớp UI "Kết quả đánh giá ban đầu") —
KHÔNG phải tính toán tự động từ SessionResult.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Enum as SAEnum, Float, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import AssessmentStatus, AssessmentType

if TYPE_CHECKING:
    from app.models.user import Patient


class Assessment(Base, TimestampMixin):
    """A clinical assessment session for a patient."""

    __tablename__ = "assessments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # Association FK — patient not deleted when assessment is deleted
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[AssessmentType] = mapped_column(
        SAEnum(AssessmentType, name="assessment_type", create_constraint=True), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[AssessmentStatus] = mapped_column(
        SAEnum(AssessmentStatus, name="assessment_status", create_constraint=True),
        nullable=False,
        default=AssessmentStatus.in_progress,
        server_default="in_progress",
    )
    notes: Mapped[Optional[str]] = mapped_column(Text())

    patient: Mapped["Patient"] = relationship(back_populates="assessments")
    # Composition: result is owned by assessment
    result: Mapped[Optional["AssessmentResult"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class AssessmentResult(Base):
    """3 chỉ số đánh giá ban đầu — 1-1 with Assessment.

    3 field accuracy_score/completion_score/fluency_score là số liệu DO BÁC SĨ HOẶC NGƯỜI
    NHÀ NHẬP TAY lúc đăng ký (khớp UI "Kết quả đánh giá ban đầu") — KHÔNG phải tính toán
    tự động từ SessionResult. Nếu sau này cần thêm 1 loại đánh giá tính tự động, tạo
    Assessment mới với type khác, KHÔNG ghi đè lên dòng ban đầu này (giữ lịch sử).

    ai_analysis: ghi chú tự do, optional, không bắt buộc.
    """

    __tablename__ = "assessment_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # Unique FK makes this a 1-1 composition
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessments.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    accuracy_score: Mapped[Optional[float]] = mapped_column(Float)    # "Độ chính xác"
    completion_score: Mapped[Optional[float]] = mapped_column(Float)  # "Độ hoàn thành"
    fluency_score: Mapped[Optional[float]] = mapped_column(Float)     # "Độ trôi chảy"
    ai_analysis: Mapped[Optional[str]] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
    )

    assessment: Mapped["Assessment"] = relationship(back_populates="result")
