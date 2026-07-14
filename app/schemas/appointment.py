"""
Pydantic schemas cho LỊCH HẸN.

Múi giờ: backend lưu/trả UTC (ISO 8601, timestamptz) — frontend tự hiển thị giờ địa phương.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, model_validator


class AppointmentCreateRequest(BaseModel):
    """POST /therapist/patients/{id}/appointments — bác sĩ đặt lịch cho bệnh nhân CỦA MÌNH."""

    starts_at: datetime
    ends_at: datetime
    location: str
    room: Optional[str] = None
    note: Optional[str] = None

    @model_validator(mode="after")
    def validate_time_range(self) -> "AppointmentCreateRequest":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at phải sau starts_at")
        return self


class AppointmentItem(BaseModel):
    """1 lịch hẹn — dùng chung cho response tạo mới + danh sách của bệnh nhân."""

    appointment_id: str
    starts_at: datetime
    ends_at: datetime
    location: str
    room: Optional[str]
    note: Optional[str]
    doctor_name: str        # full_name của bác sĩ đặt lịch
