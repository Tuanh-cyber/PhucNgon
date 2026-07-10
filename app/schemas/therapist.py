"""
Pydantic schemas cho web BÁC SĨ (Bước 13.1).

Mô hình: link bác sĩ↔bệnh nhân qua TherapyPlan.therapist_id (plan active).
Hệ thống có HAI loại bệnh nhân song song — đều HỢP LỆ:
  - có bác sĩ : therapist_id = UUID bác sĩ
  - tự do     : therapist_id = NULL (tự đăng ký, dùng app một mình)
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, EmailStr

# Danh sách loại aphasia hợp lệ khi bác sĩ nhập (validate tầng API, cột DB vẫn là
# String để không vỡ dữ liệu tự đăng ký cũ dạng text tự do).
AphasiaType = Literal[
    "Broca", "Wernicke", "Anomic", "Global", "Conduction", "Mixed", "Khác"
]


class ClaimPatientRequest(BaseModel):
    """POST /therapist/patients/claim — bác sĩ NHẬN 1 bệnh nhân đã tự đăng ký (tra theo email)."""

    email: EmailStr
    aphasia_type: Optional[AphasiaType] = None
    hospital_name: Optional[str] = None
    severity_level: Optional[str] = None
    # Baseline optional — có >=1 điểm thì tạo Assessment + AssessmentResult (như lúc register).
    accuracy_score: Optional[float] = None
    completion_score: Optional[float] = None
    fluency_score: Optional[float] = None


class ClaimPatientResponse(BaseModel):
    """Kết quả claim: claimed = vừa gán mới; updated = đã là bệnh nhân của tôi, cập nhật info."""

    patient_id: str
    full_name: str
    status: Literal["claimed", "updated"]


class TherapistPatientItem(BaseModel):
    """1 bệnh nhân trong danh sách của bác sĩ (GET /therapist/me/patients) — tối thiểu cho 13.1."""

    patient_id: str
    full_name: str
    email: str
    aphasia_type: Optional[str]
    severity_level: Optional[str]
    hospital_name: Optional[str]
