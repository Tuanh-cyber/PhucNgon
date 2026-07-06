"""Clinical report model."""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, Enum as SAEnum, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import ReportType

if TYPE_CHECKING:
    from app.models.user import Patient, Therapist


class Report(Base):
    """A generated clinical report covering a date range for a patient."""

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # Association FKs — no cascade
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False
    )
    therapist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("therapists.id"), nullable=False
    )
    type: Mapped[ReportType] = mapped_column(
        SAEnum(ReportType, name="report_type", create_constraint=True), nullable=False
    )
    period_start: Mapped[date] = mapped_column(Date(), nullable=False)
    period_end: Mapped[Optional[date]] = mapped_column(Date())
    file_url: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
    )

    patient: Mapped["Patient"] = relationship(back_populates="reports")
    therapist: Mapped["Therapist"] = relationship(back_populates="reports")
