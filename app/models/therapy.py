"""Therapy workflow: TherapyPlan → ExerciseAssignment → ExerciseSession → SessionResult.

The chain is a true composition — each parent owns its children:
  plan (delete-orphan) → assignments (delete-orphan) → sessions (delete-orphan) → results

patient_id and therapist_id on TherapyPlan, and patient_id on ExerciseSession,
are association FKs — no ORM cascade in those directions.

SessionResult maps 1-1 to ScoreResult in PhucNgon_Scoring_Engine_Spec.
The 'components' JSONB field stores the full score breakdown from the scoring engine.
"""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import PlanStatus, ResultLabel, SessionStatus, Topic

if TYPE_CHECKING:
    from app.models.content import Exercise
    from app.models.speech import SpeechRecording
    from app.models.user import Patient, Therapist


# ── Therapy Plan ──────────────────────────────────────────────────────────────
class TherapyPlan(Base, TimestampMixin):
    """A structured therapy programme assigned to a patient by a therapist."""

    __tablename__ = "therapy_plans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # Association FKs — no cascade from plan perspective
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False
    )
    # nullable: patient tự đăng ký chưa có therapist gán -> plan khởi đầu để None,
    # therapist_id sẽ được điền khi có chuyên viên nhận ca (bước sau).
    therapist_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("therapists.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[date] = mapped_column(Date(), nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date())
    status: Mapped[PlanStatus] = mapped_column(
        SAEnum(PlanStatus, name="plan_status", create_constraint=True),
        nullable=False,
        default=PlanStatus.draft,
        server_default="draft",
    )

    patient: Mapped["Patient"] = relationship(back_populates="therapy_plans")
    therapist: Mapped[Optional["Therapist"]] = relationship(back_populates="therapy_plans")
    # Composition: deleting the plan cascades to assignments → sessions → results
    assignments: Mapped[list["ExerciseAssignment"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# ── Exercise Assignment ───────────────────────────────────────────────────────
class ExerciseAssignment(Base):
    """Links an Exercise to a TherapyPlan with ordering and active flag."""

    __tablename__ = "exercise_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # Composition FK from plan
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("therapy_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Association FK to exercise content
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exercises.id"), nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    plan: Mapped["TherapyPlan"] = relationship(back_populates="assignments")
    exercise: Mapped["Exercise"] = relationship(back_populates="assignments")
    # Composition: deleting an assignment cascades to its sessions → results
    sessions: Mapped[list["ExerciseSession"]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# ── Exercise Session ──────────────────────────────────────────────────────────
class ExerciseSession(Base):
    """A patient's attempt at one ExerciseAssignment."""

    __tablename__ = "exercise_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # Composition FK from assignment
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exercise_assignments.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Denormalized association FK for efficient patient-scoped queries
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False
    )
    # PHIÊN tập (rule.md mục 3) chứa bài này — NULLABLE: luồng cũ/dữ liệu cũ không có
    # phiên vẫn hợp lệ y nguyên. Chỉ gắn khi submit kèm therapy_session_id.
    therapy_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("therapy_sessions.id")
    )
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[SessionStatus] = mapped_column(
        SAEnum(SessionStatus, name="session_status", create_constraint=True),
        nullable=False,
        default=SessionStatus.in_progress,
        server_default="in_progress",
    )

    assignment: Mapped["ExerciseAssignment"] = relationship(back_populates="sessions")
    patient: Mapped["Patient"] = relationship(back_populates="exercise_sessions")
    # Composition: deleting session cascades to results
    results: Mapped[list["SessionResult"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# ── Session Result ────────────────────────────────────────────────────────────
class SessionResult(Base):
    """Per-attempt scoring record — maps to ScoreResult in the Scoring Engine spec.

    This is the 'session_items' table referenced in PhucNgon_Scoring_Engine_Spec.
    'components' JSONB stores the full breakdown: phoneme_score, tonal_score,
    fluency_score, duration_penalty, etc. as produced by the scoring engine.
    'selected_vocab_id' is only populated for command_identification exercises.
    """

    __tablename__ = "session_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # Composition FK from session
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exercise_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    transcript: Mapped[Optional[str]] = mapped_column(String(500))
    # selected_vocab_id: populated only for command_identification exercises
    selected_vocab_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    audio_duration_s: Mapped[Optional[float]]
    asr_confidence: Mapped[Optional[float]]
    score: Mapped[Optional[float]]
    raw_score: Mapped[Optional[float]]
    weighted_score: Mapped[Optional[float]]
    is_correct: Mapped[Optional[bool]]
    components: Mapped[Any] = mapped_column(JSONB, nullable=False)
    result: Mapped[ResultLabel] = mapped_column(
        # values_callable bắt buộc vì ResultLabel.pass_ có value="pass" (khác name="pass_")
        SAEnum(ResultLabel, name="result_label", create_constraint=True,
               values_callable=lambda x: [e.value for e in x]),
        nullable=False
    )
    used_fallback_audio: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
    )

    session: Mapped["ExerciseSession"] = relationship(back_populates="results")
    # Composition: deleting a result cascades to its recording → transcription → analysis → feedback
    recording: Mapped[Optional["SpeechRecording"]] = relationship(
        back_populates="result",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
        foreign_keys="[SpeechRecording.result_id]",
    )


# ── Topic Progress ────────────────────────────────────────────────────────────
class TopicProgress(Base):
    """Tiến trình vocab level BỀN VỮNG của 1 patient theo TỪNG topic (rule.md mục 2).

    Khác ProgressionState (scoring_service) — object trong bộ nhớ, reset mỗi session.
    Bảng này lưu xuyên session: 3 lần liên tiếp score >= 80 cùng topic -> +1 level (tối đa 3);
    1 lần < 80 -> reset counter. Được cập nhật trong submit_attempt() cùng transaction với
    SessionResult.
    """

    __tablename__ = "topic_progress"
    __table_args__ = (
        CheckConstraint("current_level BETWEEN 1 AND 3", name="ck_topic_progress_level"),
        UniqueConstraint("patient_id", "topic", name="uq_topic_progress_patient_topic"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
    )
    topic: Mapped[Topic] = mapped_column(
        SAEnum(Topic, name="topic", create_constraint=True), nullable=False
    )
    current_level: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    consecutive_high_scores: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
        nullable=False,
    )
