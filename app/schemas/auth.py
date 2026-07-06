"""
Pydantic schemas cho đăng ký / đăng nhập.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, EmailStr

from app.models.enums import Gender


class PatientRegisterRequest(BaseModel):
    """Đăng ký tài khoản bệnh nhân (khớp UI đăng ký 3 bước)."""

    full_name: str
    email: EmailStr
    password: str
    phone_number: Optional[str] = None  # SĐT của BỆNH NHÂN
    date_of_birth: date
    gender: Gender
    # "Địa chỉ" + "SĐT người chăm sóc" trong UI đăng ký. Lưu vào Profile (bảng riêng, quan hệ
    # 1-1 với User), KHÔNG lưu thẳng trên Patient. Cả 2 OPTIONAL.
    #   address          -> Profile.address
    #   caregiver_phone  -> Profile.emergency_contact (SĐT liên hệ khẩn/người chăm sóc)
    address: Optional[str] = None
    caregiver_phone: Optional[str] = None
    aphasia_type: Optional[str] = None
    severity_level: Optional[str] = None
    hospital_name: Optional[str] = None
    referring_doctor_name: Optional[str] = None
    # 3 chỉ số "Kết quả đánh giá ban đầu" do bác sĩ/người nhà nhập tay lúc đăng ký.
    # OPTIONAL — không phải lúc nào cũng có sẵn số liệu. Thang 0-100.
    accuracy_score: Optional[float] = None    # "Độ chính xác"
    completion_score: Optional[float] = None  # "Độ hoàn thành"
    fluency_score: Optional[float] = None     # "Độ trôi chảy"


class TherapistRegisterRequest(BaseModel):
    """Đăng ký tài khoản chuyên viên trị liệu."""

    full_name: str
    email: EmailStr
    password: str
    phone_number: Optional[str] = None
    license_no: str
    specialization: Optional[str] = None


class LoginRequest(BaseModel):
    """Đăng nhập bằng email + password."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Response chứa JWT access token sau khi đăng ký/đăng nhập thành công."""

    access_token: str
    token_type: str = "bearer"
    role: str


class MeResponse(BaseModel):
    """Thông tin user hiện tại cho GET /auth/me (frontend kiểm tra token còn hợp lệ)."""

    user_id: str
    full_name: str
    email: EmailStr
    role: str
