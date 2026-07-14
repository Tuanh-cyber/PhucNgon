"""SQLAlchemy ORM models — import toàn bộ để Alembic autogenerate detect được Base.metadata."""

# Base phải import trước tất cả
from app.models.base import Base, TimestampMixin

# Enums
from app.models.enums import (
    AssessmentStatus,
    AssessmentType,
    CommandMode,
    ExerciseType,
    Gender,
    NotificationType,
    PlanStatus,
    ReportType,
    ResultLabel,
    SessionStatus,
    Topic,
    UserRole,
    UserStatus,
    WordType,
)

# Models — thứ tự import theo FK dependency
from app.models.user import Caregiver, Patient, Profile, Therapist, User
from app.models.assessment import Assessment, AssessmentResult
from app.models.content import (
    CommandAsset,
    Exercise,
    SentenceInstanceAsset,
    SentenceTemplateAsset,
    VocabularyAsset,
)
from app.models.therapy import (
    ExerciseAssignment,
    ExerciseSession,
    SessionResult,
    TherapyPlan,
    TopicProgress,
)
from app.models.speech import AiFeedback, AphasiaAnalysis, SpeechRecording, Transcription
from app.models.notification import Notification
from app.models.appointment import Appointment
from app.models.report import Report

__all__ = [
    # Base
    "Base",
    "TimestampMixin",
    # Enums
    "UserRole", "UserStatus", "Gender",
    "AssessmentType", "AssessmentStatus",
    "PlanStatus", "SessionStatus",
    "ExerciseType", "CommandMode",
    "Topic", "WordType", "ResultLabel",
    "NotificationType", "ReportType",
    # Models
    "User", "Patient", "Therapist", "Caregiver", "Profile",
    "Assessment", "AssessmentResult",
    "VocabularyAsset", "CommandAsset",
    "SentenceTemplateAsset", "SentenceInstanceAsset", "Exercise",
    "TherapyPlan", "ExerciseAssignment", "ExerciseSession", "SessionResult",
    "TopicProgress",
    "SpeechRecording", "Transcription", "AphasiaAnalysis", "AiFeedback",
    "Notification",
    "Appointment", "Appointment", "Report",
]
