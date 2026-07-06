"""Speech processing chain: SpeechRecording → Transcription → AphasiaAnalysis → AiFeedback.

Each step is a 1-1 composition of the previous — CASCADE all the way down.
result_id on SpeechRecording is nullable (0..1) because CMD Mode 1
(recognition via image tap) does not capture audio.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Float, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.therapy import SessionResult


class SpeechRecording(Base):
    """Raw audio file captured during an exercise attempt.

    result_id is nullable — absent when CMD Mode 1 (no audio captured).
    The unique constraint makes this a 0..1 to 1 relationship with SessionResult.
    """

    __tablename__ = "speech_recordings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # Optional FK with unique — 0..1 relationship to SessionResult
    result_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session_results.id", ondelete="CASCADE"),
        unique=True,
    )
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    duration_sec: Mapped[float] = mapped_column(Float, nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    result: Mapped[Optional["SessionResult"]] = relationship(
        back_populates="recording",
        foreign_keys=[result_id],
    )
    # Composition: deleting recording cascades to transcription
    transcription: Mapped[Optional["Transcription"]] = relationship(
        back_populates="recording",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class Transcription(Base):
    """ASR output for a speech recording — 1-1 composition of SpeechRecording."""

    __tablename__ = "transcriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    recording_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("speech_recordings.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    raw_text: Mapped[str] = mapped_column(String(500), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    language: Mapped[str] = mapped_column(
        String(10), nullable=False, default="vi", server_default="vi"
    )

    recording: Mapped["SpeechRecording"] = relationship(back_populates="transcription")
    # Composition: cascades to analysis
    analysis: Mapped[Optional["AphasiaAnalysis"]] = relationship(
        back_populates="transcription",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class AphasiaAnalysis(Base):
    """Aphasia-specific error analysis on a transcription — 1-1 composition."""

    __tablename__ = "aphasia_analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    transcription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transcriptions.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    # JSONB: list of {error_type, token, position} dicts
    detected_errors: Mapped[Any] = mapped_column(JSONB, nullable=False)
    severity_score: Mapped[Optional[float]]

    transcription: Mapped["Transcription"] = relationship(back_populates="analysis")
    # Composition: cascades to AI feedback
    feedback: Mapped[Optional["AiFeedback"]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class AiFeedback(Base):
    """Structured AI-generated feedback from an aphasia analysis — 1-1 composition."""

    __tablename__ = "ai_feedbacks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("aphasia_analyses.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    strengths: Mapped[Optional[str]] = mapped_column(String(500))
    weaknesses: Mapped[Optional[str]] = mapped_column(String(500))
    suggestions: Mapped[Optional[str]] = mapped_column(String(500))

    analysis: Mapped["AphasiaAnalysis"] = relationship(back_populates="feedback")
