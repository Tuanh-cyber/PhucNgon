"""All shared enums — each is both a Python enum.Enum and maps to a native PostgreSQL ENUM type.

Naming convention for SA Enum: snake_case name matches the enum class name in lower_snake.
create_constraint=True ensures PostgreSQL creates the TYPE in the schema.
"""

import enum


class UserRole(enum.Enum):
    patient   = "patient"
    therapist = "therapist"
    caregiver = "caregiver"
    admin     = "admin"


class UserStatus(enum.Enum):
    active    = "active"
    inactive  = "inactive"
    suspended = "suspended"


class Gender(enum.Enum):
    male   = "male"
    female = "female"
    other  = "other"


class AssessmentType(enum.Enum):
    language      = "language"
    speech        = "speech"
    cognitive     = "cognitive"
    comprehension = "comprehension"


class AssessmentStatus(enum.Enum):
    in_progress = "in_progress"
    completed   = "completed"
    cancelled   = "cancelled"


class PlanStatus(enum.Enum):
    draft     = "draft"
    active    = "active"
    paused    = "paused"
    completed = "completed"
    expired   = "expired"


class SessionStatus(enum.Enum):
    in_progress = "in_progress"
    submitted   = "submitted"
    graded      = "graded"
    cancelled   = "cancelled"


class ExerciseType(enum.Enum):
    naming               = "naming"
    command_identification = "command_identification"
    sentence_building    = "sentence_building"


class CommandMode(enum.Enum):
    recognition = "recognition"
    repetition  = "repetition"


class Topic(enum.Enum):
    daily_activity  = "daily_activity"
    food_drink      = "food_drink"
    household_item  = "household_item"
    family          = "family"
    body_part       = "body_part"
    number          = "number"


class WordType(enum.Enum):
    noun      = "noun"
    verb      = "verb"
    adjective = "adjective"


class ResultLabel(enum.Enum):
    pass_     = "pass"
    near      = "near"
    retry     = "retry"
    skip      = "skip"
    correct   = "correct"
    incorrect = "incorrect"
    invalid   = "invalid"


class NotificationType(enum.Enum):
    reminder      = "reminder"
    alert         = "alert"
    new_feedback  = "new_feedback"
    plan_updated  = "plan_updated"
    system        = "system"


class ReportType(enum.Enum):
    progress_summary   = "progress_summary"
    assessment_report  = "assessment_report"
    therapy_report     = "therapy_report"
