"""Content/exercise catalogue models — bám sát Exercise_spec.md và Taxonomy.md.

Exercise.target_* exclusivity rule (enforced by DB CheckConstraint + docstring):
  - ExerciseType.naming            → only target_vocab_id IS NOT NULL
  - ExerciseType.command_identification → only target_vocab_id IS NOT NULL (resolved from CommandAsset)
  - ExerciseType.sentence_building → only target_sentence_instance_id IS NOT NULL
The other two target columns MUST be NULL for any given exercise type.
CheckConstraint name: ck_exercise_target_exclusivity
"""

import uuid
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import CommandMode, ExerciseType, Topic, WordType

if TYPE_CHECKING:
    from app.models.therapy import ExerciseAssignment


# ── Vocabulary asset ─────────────────────────────────────────────────────────
class VocabularyAsset(Base):
    """A single vocabulary item (word/picture) used across exercises."""

    __tablename__ = "vocabulary_assets"
    __table_args__ = (
        CheckConstraint("vocab_level BETWEEN 1 AND 3", name="ck_vocabulary_vocab_level"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    canonical_word: Mapped[str] = mapped_column(String(255), nullable=False)
    vocab_level: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_answers: Mapped[Any] = mapped_column(JSONB, nullable=False)
    accepted_classifiers: Mapped[Optional[Any]] = mapped_column(JSONB)
    image_file: Mapped[Optional[str]] = mapped_column(String(255))
    audio_file: Mapped[Optional[str]] = mapped_column(String(255))
    topic: Mapped[Topic] = mapped_column(
        SAEnum(Topic, name="topic", create_constraint=True), nullable=False
    )
    word_type: Mapped[WordType] = mapped_column(
        SAEnum(WordType, name="word_type", create_constraint=True), nullable=False
    )

    exercises_as_vocab: Mapped[list["Exercise"]] = relationship(
        back_populates="target_vocab",
        foreign_keys="[Exercise.target_vocab_id]",
    )
    command_assets: Mapped[list["CommandAsset"]] = relationship(
        back_populates="target_vocab",
    )
    sentence_instances: Mapped[list["SentenceInstanceAsset"]] = relationship(
        back_populates="vocab",
    )


# ── Command asset ─────────────────────────────────────────────────────────────
class CommandAsset(Base):
    """An audio command paired with a target vocab and distractors (command_identification)."""

    __tablename__ = "command_assets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    command_text: Mapped[str] = mapped_column(String(500), nullable=False)
    command_audio_file: Mapped[Optional[str]] = mapped_column(String(255))
    target_vocab_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vocabulary_assets.id"),
        nullable=False,
    )
    # JSON array of UUID strings for distractor VocabularyAsset rows
    # Populated by service layer at runtime, not seeded from Excel
    distractor_vocab_ids: Mapped[Optional[Any]] = mapped_column(JSONB)

    target_vocab: Mapped["VocabularyAsset"] = relationship(back_populates="command_assets")
    exercises_as_command: Mapped[list["Exercise"]] = relationship(
        back_populates="target_command",
        foreign_keys="[Exercise.target_command_id]",
    )


# ── Sentence template asset ───────────────────────────────────────────────────
class SentenceTemplateAsset(Base):
    """A sentence template with a blank slot (sentence_building exercises)."""

    __tablename__ = "sentence_template_assets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    template: Mapped[str] = mapped_column(String(255), nullable=False)
    topic_constraint: Mapped[Topic] = mapped_column(
        SAEnum(Topic, name="topic", create_constraint=True), nullable=False
    )

    instances: Mapped[list["SentenceInstanceAsset"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# ── Sentence instance asset ───────────────────────────────────────────────────
class SentenceInstanceAsset(Base):
    """A specific sentence built from a template + a vocabulary word."""

    __tablename__ = "sentence_instance_assets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sentence_template_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    vocab_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vocabulary_assets.id"),
        nullable=False,
    )
    full_sentence: Mapped[str] = mapped_column(String(500), nullable=False)
    accepted_answers: Mapped[Any] = mapped_column(JSONB, nullable=False)
    audio_file: Mapped[Optional[str]] = mapped_column(String(255))

    template: Mapped["SentenceTemplateAsset"] = relationship(back_populates="instances")
    vocab: Mapped["VocabularyAsset"] = relationship(back_populates="sentence_instances")
    exercises_as_sentence: Mapped[list["Exercise"]] = relationship(
        back_populates="target_sentence_instance",
        foreign_keys="[Exercise.target_sentence_instance_id]",
    )


# ── Exercise ─────────────────────────────────────────────────────────────────
class Exercise(Base, TimestampMixin):
    """A single assignable exercise unit.

    Target FK exclusivity (enforced by ck_exercise_target_exclusivity):
      naming            → target_vocab_id only
      command_identification → target_vocab_id only (resolved from CommandAsset.target_vocab_id,
                         target_command_id is reserved for future use)
      sentence_building → target_sentence_instance_id only
    """

    __tablename__ = "exercises"
    __table_args__ = (
        CheckConstraint(
            "(exercise_type = 'naming'"
            "  AND target_vocab_id IS NOT NULL"
            "  AND target_command_id IS NULL"
            "  AND target_sentence_instance_id IS NULL)"
            " OR (exercise_type = 'command_identification'"
            "  AND target_vocab_id IS NOT NULL"
            "  AND target_command_id IS NULL"
            "  AND target_sentence_instance_id IS NULL)"
            " OR (exercise_type = 'sentence_building'"
            "  AND target_sentence_instance_id IS NOT NULL"
            "  AND target_vocab_id IS NULL"
            "  AND target_command_id IS NULL)",
            name="ck_exercise_target_exclusivity",
        ),
        CheckConstraint("vocab_level BETWEEN 1 AND 3", name="ck_exercise_vocab_level"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    exercise_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    exercise_type: Mapped[ExerciseType] = mapped_column(
        SAEnum(ExerciseType, name="exercise_type", create_constraint=True), nullable=False
    )
    # mode: only relevant for command_identification exercises
    mode: Mapped[Optional[CommandMode]] = mapped_column(
        SAEnum(CommandMode, name="command_mode", create_constraint=True)
    )
    topic: Mapped[Topic] = mapped_column(
        SAEnum(Topic, name="topic", create_constraint=True), nullable=False
    )
    vocab_level: Mapped[int] = mapped_column(Integer, nullable=False)
    suitable_profiles: Mapped[Any] = mapped_column(JSONB, nullable=False)

    # Exactly one of the three below is non-null per row (enforced by CheckConstraint above)
    target_vocab_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vocabulary_assets.id")
    )
    target_command_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("command_assets.id")
    )
    target_sentence_instance_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sentence_instance_assets.id")
    )
    duration_expected: Mapped[Optional[float]] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    target_vocab: Mapped[Optional["VocabularyAsset"]] = relationship(
        back_populates="exercises_as_vocab",
        foreign_keys=[target_vocab_id],
    )
    target_command: Mapped[Optional["CommandAsset"]] = relationship(
        back_populates="exercises_as_command",
        foreign_keys=[target_command_id],
    )
    target_sentence_instance: Mapped[Optional["SentenceInstanceAsset"]] = relationship(
        back_populates="exercises_as_sentence",
        foreign_keys=[target_sentence_instance_id],
    )
    assignments: Mapped[list["ExerciseAssignment"]] = relationship(
        back_populates="exercise",
    )
