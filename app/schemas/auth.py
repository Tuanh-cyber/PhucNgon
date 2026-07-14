"""
Pydantic schemas cho đăng ký / đăng nhập.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import Gender
from app.services.phone_service import normalize_phone


class PatientRegisterRequest(BaseModel):
    """Đăng ký tài khoản bệnh nhân (khớp UI đăng ký 3 bước)."""

    full_name: str
    email: EmailStr
    password: str
    # SĐT của BỆNH NHÂN — BẮT BUỘC (Mô hình A: bác sĩ claim theo sđt). Validator dưới
    # chuẩn hóa và LƯU DẠNG CHUẨN "0xxxxxxxxx"; số rác -> 422. Cột users.phone_number
    # vẫn nullable (dùng chung mọi role — bác sĩ không bắt buộc), chỉ ÉP ở tầng API này.
    phone_number: str
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

    @field_validator("phone_number")
    @classmethod
    def validate_patient_phone(cls, v: str) -> str:
        """Chuẩn hóa sđt bệnh nhân; không hợp lệ -> 422. Giá trị LƯU = dạng chuẩn hóa."""
        norm = normalize_phone(v)
        if norm is None:
            raise ValueError(
                "Số điện thoại không hợp lệ (cần số VN 10-11 chữ số, vd 0912345678)"
            )
        return norm

    # caregiver_phone (người thân): GIỮ optional, KHÔNG ép định dạng.


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


class ChangePasswordRequest(BaseModel):
    """POST /auth/change-password — user ĐANG ĐĂNG NHẬP tự đổi mật khẩu của mình (mọi role).

    new_password tối thiểu 6 ký tự (đăng ký hiện CHƯA có rule độ dài — áp ở đây trước,
    đồng bộ ngược cho register sau nếu team chốt)."""

    current_password: str
    new_password: str = Field(min_length=6)


class ChangePasswordResponse(BaseModel):
    message: str
