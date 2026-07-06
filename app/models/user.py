"""User hierarchy using joined-table inheritance: User → Patient | Therapist | Caregiver.

Profile is a 1-1 composition owned by User (ON DELETE CASCADE).
Admin role uses the base User table only — no subclass table.
"""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Date, Enum as SAEnum, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import Gender, UserRole, UserStatus

if TYPE_CHECKING:
    from app.models.assessment import Assessment
    from app.models.notification import Notification
    from app.models.report import Report
    from app.models.therapy import ExerciseSession, TherapyPlan


# ── Base user (shared columns) ──────────────────────────────────────────────
class User(Base, TimestampMixin):
    """Base user table — shared by all roles. Admin role lives here only."""

    __tablename__ = "users"
    # polymorphic_identity phải là enum member UserRole.* (KHÔNG phải string thô):
    # cột discriminator `role` là Mapped[UserRole] nên khi load từ DB, giá trị trả về là
    # UserRole member — identity string "admin" sẽ không khớp -> lỗi polymorphic loading.
    __mapper_args__ = {
        "polymorphic_on": "role",
        "polymorphic_identity": UserRole.admin,
    }

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[Optional[str]] = mapped_column(String(20))
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", create_constraint=True), nullable=False
    )
    status: Mapped[UserStatus] = mapped_column(
        SAEnum(UserStatus, name="user_status", create_constraint=True),
        nullable=False,
        default=UserStatus.active,
        server_default="active",
    )

    # ── Compositions (cascade delete) ──
    profile: Mapped[Optional["Profile"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# ── Patient ─────────────────────────────────────────────────────────────────
class Patient(User):
    """Extends users with clinical profile. FK cascades from users."""

    __tablename__ = "patients"
    __mapper_args__ = {"polymorphic_identity": UserRole.patient}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    date_of_birth: Mapped[date] = mapped_column(Date(), nullable=False)
    gender: Mapped[Gender] = mapped_column(
        SAEnum(Gender, name="gender", create_constraint=True), nullable=False
    )
    native_language: Mapped[str] = mapped_column(
        String(50), nullable=False, default="vi", server_default="vi"
    )
    diagnosis_date: Mapped[Optional[date]] = mapped_column(Date())
    aphasia_type: Mapped[Optional[str]] = mapped_column(String(100))
    severity_level: Mapped[Optional[str]] = mapped_column(String(50))
    # "Bệnh viện đã khám" / "Bác sĩ phụ trách" trong UI đăng ký.
    # LƯU Ý: đây là bệnh viện + bác sĩ NGOÀI ĐỜI THẬT, ghi tự do bằng text — KHÔNG phải
    # Foreign Key tới bảng therapists trong hệ thống (2 khái niệm hoàn toàn khác nhau:
    # therapist trong hệ thống là tài khoản dùng app; referring_doctor là bác sĩ đã khám
    # cho bệnh nhân ở bệnh viện, có thể không bao giờ dùng app).
    hospital_name: Mapped[Optional[str]] = mapped_column(String(255))
    referring_doctor_name: Mapped[Optional[str]] = mapped_column(String(255))

    # ── Associations (no ORM cascade — only DB FK may cascade) ──
    caregivers: Mapped[list["Caregiver"]] = relationship(
        back_populates="patient",
        foreign_keys="[Caregiver.patient_id]",
    )
    assessments: Mapped[list["Assessment"]] = relationship(
        back_populates="patient",
        # DB FK assessments.patient_id là ON DELETE CASCADE — để DB tự xoá assessment khi
        # patient bị xoá. passive_deletes=True ngăn ORM nullify patient_id (NOT NULL -> lỗi).
        passive_deletes=True,
    )
    therapy_plans: Mapped[list["TherapyPlan"]] = relationship(
        back_populates="patient",
    )
    exercise_sessions: Mapped[list["ExerciseSession"]] = relationship(
        back_populates="patient",
    )
    reports: Mapped[list["Report"]] = relationship(
        back_populates="patient",
    )


# ── Therapist ────────────────────────────────────────────────────────────────
class Therapist(User):
    """Extends users with professional credentials."""

    __tablename__ = "therapists"
    __mapper_args__ = {"polymorphic_identity": UserRole.therapist}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    license_no: Mapped[str] = mapped_column(String(100), nullable=False)
    specialization: Mapped[Optional[str]] = mapped_column(String(255))
    qualification: Mapped[Optional[str]] = mapped_column(String(255))
    organization: Mapped[Optional[str]] = mapped_column(String(255))

    # ── Associations ──
    therapy_plans: Mapped[list["TherapyPlan"]] = relationship(
        back_populates="therapist",
    )
    reports: Mapped[list["Report"]] = relationship(
        back_populates="therapist",
    )


# ── Caregiver ────────────────────────────────────────────────────────────────
class Caregiver(User):
    """Extends users with caregiver-patient link. patient_id is an association FK."""

    __tablename__ = "caregivers"
    __mapper_args__ = {"polymorphic_identity": UserRole.caregiver}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    relation_to_patient: Mapped[Optional[str]] = mapped_column(String(100))
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Association FK — no ORM cascade
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id"),
        nullable=False,
    )

    patient: Mapped["Patient"] = relationship(
        back_populates="caregivers",
        foreign_keys=[patient_id],
    )


# ── Profile (1-1 composition of User) ────────────────────────────────────────
class Profile(Base, TimestampMixin):
    """Extended user profile — owned by User, deleted if user is deleted."""

    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    address: Mapped[Optional[str]] = mapped_column(String(500))
    emergency_contact: Mapped[Optional[str]] = mapped_column(String(255))
    medical_history: Mapped[Optional[str]] = mapped_column(Text())
    profile_image_url: Mapped[Optional[str]] = mapped_column(String(500))

    user: Mapped["User"] = relationship(back_populates="profile")
