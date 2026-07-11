"""
Pydantic schemas cho web BÁC SĨ (Bước 13.1).

Mô hình: link bác sĩ↔bệnh nhân qua TherapyPlan.therapist_id (plan active).
Hệ thống có HAI loại bệnh nhân song song — đều HỢP LỆ:
  - có bác sĩ : therapist_id = UUID bác sĩ
  - tự do     : therapist_id = NULL (tự đăng ký, dùng app một mình)
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

from app.schemas.assessment import ProgressDashboardResponse

# Danh sách loại aphasia hợp lệ khi bác sĩ nhập (validate tầng API, cột DB vẫn là
# String để không vỡ dữ liệu tự đăng ký cũ dạng text tự do).
AphasiaType = Literal[
    "Broca", "Wernicke", "Anomic", "Global", "Conduction", "Mixed", "Khác"
]


class ClaimPatientRequest(BaseModel):
    """POST /therapist/patients/claim — bác sĩ NHẬN 1 bệnh nhân (khớp theo SỐ ĐIỆN THOẠI
    đã chuẩn hóa — Mô hình A; nhận mọi định dạng 0912..., +84 91..., có chấm/khoảng trắng)."""

    phone: str
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
    """1 dòng bảng bệnh nhân của bác sĩ (GET /therapist/me/patients — 13.2, khớp mockup Ảnh 1)."""

    patient_id: str
    full_name: str
    email: str
    aphasia_type: Optional[str]
    severity_level: Optional[str]
    hospital_name: Optional[str]
    # ── Cột số liệu (13.2) ──
    progress_week: Optional[float]      # % hoàn thành CẤP PLAN (completion có sẵn); None = chưa có dữ liệu
    avg_score_2days: Optional[float]    # TB điểm 2 ngày qua; None = không có buổi có điểm
    streak_days: int                    # chuỗi ngày luyện liên tiếp (tái dùng streak dashboard)
    sessions_per_week: int              # số NGÀY có luyện trong 7 ngày gần nhất (0..7, hiển thị x/7)
    status: Literal["good", "attention"]  # attention = 0 buổi graded trong 3 ngày qua


class TherapistPatientListResponse(BaseModel):
    """Bảng bệnh nhân có phân trang: total = tổng SAU filter, items = trang hiện tại."""

    total: int
    items: list[TherapistPatientItem]


class AttentionPatient(BaseModel):
    """1 bệnh nhân trong banner 'N bệnh nhân chưa luyện tập 3 ngày'."""

    patient_id: str
    full_name: str


class DashboardSummaryResponse(BaseModel):
    """4 thẻ + banner đầu dashboard bác sĩ (GET /therapist/dashboard-summary — 13.3).
    MỌI con số tính trên TẬP bệnh nhân của bác sĩ đăng nhập."""

    total_patients: int
    practicing: int                       # ≥1 buổi graded trong 7 ngày qua
    need_attention: int                   # 0 buổi graded trong 3 ngày qua
    weekly_completion: Optional[float]    # TB progress_week across bệnh nhân (bỏ None); None = chưa ai có dữ liệu
    attention_list: list[AttentionPatient]


class PatientHeader(BaseModel):
    """Khối hồ sơ đầu màn chi tiết (13.4, Ảnh 2)."""

    full_name: str
    age: int                              # tính từ date_of_birth
    aphasia_type: Optional[str]
    severity_level: Optional[str]
    hospital_name: Optional[str]
    doctor_name: str                      # = full_name bác sĩ đang đăng nhập


class InsightItem(BaseModel):
    """1 câu nhận xét rule-based từ 3 metrics — type để frontend tô màu."""

    type: Literal["ok", "warn"]
    text: str


class PatientStats3(BaseModel):
    """3 chỉ số thành phần (mục 'Phân tích thành phần' Ảnh 2) — None = chưa có dữ liệu."""

    accuracy_score: Optional[float]
    completion_score: Optional[float]
    fluency_score: Optional[float]


class TherapistPatientDetailResponse(BaseModel):
    """Chi tiết 1 bệnh nhân của tôi (GET /therapist/patients/{id} — 13.4, Ảnh 2)."""

    patient: PatientHeader
    dashboard: ProgressDashboardResponse    # tái dùng nguyên dashboard app bệnh nhân
    stats: PatientStats3                    # 3 chỉ số thành phần (nguồn của insight)
    avg_score_day: Optional[float]          # TB điểm/ngày trên 7 ngày (bỏ ngày trống)
    sessions_per_week: int                  # số ngày có luyện trong 7 ngày gần nhất (x/7)
    score_delta_vs_last_week: Optional[float]  # TB 7 ngày này - TB 7 ngày trước; None nếu thiếu 1 cửa sổ
    insight: InsightItem
