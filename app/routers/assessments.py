"""
Router: assessments — dữ liệu đánh giá của bệnh nhân.

GET /patients/me/initial-assessment: dữ liệu cho màn "Kết quả đánh giá ban đầu"
(4 field chẩn đoán từ hồ sơ Patient + 3 chỉ số do bác sĩ/người nhà nhập tay lúc đăng ký).
GET /patients/me/stats: 3 chỉ số TÍNH TỰ ĐỘNG từ lịch sử làm bài thật (SessionResult).
GET /patients/me/recommended-exercises: gợi ý 3 loại bài theo profile bệnh (rule.md).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.appointment import Appointment
from app.models.assessment import Assessment, AssessmentResult
from app.models.enums import UserRole
from app.models.user import Patient, Therapist, User
from app.routers.auth import get_current_user
from app.schemas.appointment import AppointmentItem
from app.schemas.assessment import (
    PatientProfileResponse,
    InitialAssessmentResponse,
    PatientStatsResponse,
    ProgressDashboardResponse,
)
from app.schemas.content import RecommendedExercise
from app.schemas.plan import EXERCISE_TYPE_DISPLAY_NAME
from app.services.plan_service import PROFILE_EXERCISE_WEIGHTS, aphasia_type_to_profile
from app.services.stats_service import compute_patient_stats, compute_progress_dashboard

router = APIRouter(prefix="/patients", tags=["assessments"])


@router.get("/me/initial-assessment", response_model=InitialAssessmentResponse)
def get_initial_assessment(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Dữ liệu cho màn "Kết quả đánh giá ban đầu" của bệnh nhân đang đăng nhập.

    - 4 field chẩn đoán (aphasia_type/severity_level/hospital_name/referring_doctor_name)
      lấy trực tiếp từ hồ sơ Patient.
    - 3 chỉ số điểm (accuracy/completion/fluency) lấy từ AssessmentResult của Assessment
      gần nhất. Nếu bác sĩ chưa nhập lúc đăng ký (KHÔNG có assessment nào) -> trả 3 field
      điểm = None, KHÔNG trả 404 (đây là trạng thái hợp lệ, không phải lỗi).
    """
    if current_user.role != UserRole.patient:
        raise HTTPException(
            status_code=403,
            detail="Chỉ bệnh nhân mới xem được đánh giá ban đầu của mình",
        )

    # current_user đã là Patient nhờ polymorphic loading, nhưng ép kiểu cho rõ ràng.
    patient: Patient = current_user  # type: ignore[assignment]

    # Assessment gần nhất của patient này (nếu có) + result đi kèm.
    result = (
        db.query(AssessmentResult)
        .join(Assessment, AssessmentResult.assessment_id == Assessment.id)
        .filter(Assessment.patient_id == patient.id)
        .order_by(Assessment.started_at.desc())
        .first()
    )

    return InitialAssessmentResponse(
        aphasia_type=patient.aphasia_type,
        severity_level=patient.severity_level,
        hospital_name=patient.hospital_name,
        referring_doctor_name=patient.referring_doctor_name,
        accuracy_score=result.accuracy_score if result else None,
        completion_score=result.completion_score if result else None,
        fluency_score=result.fluency_score if result else None,
    )


@router.get("/me/stats", response_model=PatientStatsResponse)
def get_my_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    3 chỉ số Độ chính xác / Hoàn thành / Trôi chảy — TÍNH TỰ ĐỘNG từ lịch sử làm bài thật.

    Đây là số liệu TÍNH TỰ ĐỘNG từ SessionResult, KHÁC với
    /patients/me/initial-assessment (Bước 11 — số liệu bác sĩ nhập tay lúc đăng ký, cố định
    không đổi). Dashboard bác sĩ (Module 9, sau này) PHẢI gọi lại đúng compute_patient_stats(),
    KHÔNG viết công thức riêng.

    Field nào = None nghĩa là "chưa có dữ liệu để tính" (KHÔNG phải điểm 0).
    """
    if current_user.role != UserRole.patient:
        raise HTTPException(
            status_code=403,
            detail="Chỉ bệnh nhân mới xem được chỉ số tiến độ của mình",
        )

    stats = compute_patient_stats(db, current_user.id)
    return PatientStatsResponse(**stats)


@router.get("/me/profile", response_model=PatientProfileResponse)
def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hồ sơ của patient đang đăng nhập — màn 'Tài khoản' app bệnh nhân (chỉ xem)."""
    if current_user.role != UserRole.patient:
        raise HTTPException(status_code=403, detail="Chỉ bệnh nhân mới xem được hồ sơ của mình")

    patient = db.query(Patient).filter(Patient.id == current_user.id).one()
    return PatientProfileResponse(
        full_name=patient.full_name,
        email=patient.email,
        phone_number=patient.phone_number,
        date_of_birth=patient.date_of_birth.isoformat(),
        gender=patient.gender.value,
        severity_level=patient.severity_level,
        aphasia_type=patient.aphasia_type,
        hospital_name=patient.hospital_name,
    )


@router.get("/me/appointments", response_model=list[AppointmentItem])
def get_my_appointments(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Lịch hẹn của bệnh nhân đang đăng nhập trong khoảng ngày [from, to] (theo starts_at).
    Mặc định: từ đầu THÁNG TRƯỚC đến hết THÁNG SAU (tháng hiện tại ±1).
    Giờ trả về là UTC (ISO 8601) — frontend tự hiển thị giờ địa phương. Sắp theo starts_at.
    """
    if current_user.role != UserRole.patient:
        raise HTTPException(status_code=403, detail="Chỉ bệnh nhân mới xem được lịch hẹn của mình")

    today = date.today()
    if date_from is None:
        # ngày 1 của tháng trước
        date_from = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    if date_to is None:
        # ngày cuối của tháng sau = (ngày 1 của tháng+2) - 1
        first_next = (today.replace(day=1) + timedelta(days=62)).replace(day=1)
        date_to = first_next - timedelta(days=1)

    start_bound = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
    end_bound = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)

    rows = (
        db.query(Appointment, Therapist)
        .join(Therapist, Appointment.therapist_id == Therapist.id)
        .filter(
            Appointment.patient_id == current_user.id,
            Appointment.starts_at >= start_bound,
            Appointment.starts_at < end_bound,
        )
        .order_by(Appointment.starts_at)
        .all()
    )
    return [
        AppointmentItem(
            appointment_id=str(a.id),
            starts_at=a.starts_at,
            ends_at=a.ends_at,
            location=a.location,
            room=a.room,
            note=a.note,
            doctor_name=t.full_name,
        )
        for a, t in rows
    ]


@router.get("/me/progress-dashboard", response_model=ProgressDashboardResponse)
def get_progress_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Dữ liệu dashboard tiến trình trên trang chủ bệnh nhân — 3 nhóm:
    daily_scores (biểu đồ 7 ngày) / streak (chuỗi ngày + lịch 30 ngày) /
    difficult_words (tối đa 10 từ hay sai, heuristic MVP).

    Patient mới chưa làm bài: daily_scores 7 phần tử toàn avg_score=null,
    streak=0, difficult_words=[] — KHÔNG trả 404.
    """
    if current_user.role != UserRole.patient:
        raise HTTPException(
            status_code=403,
            detail="Chỉ bệnh nhân mới xem được tiến trình của mình",
        )

    return ProgressDashboardResponse(**compute_progress_dashboard(db, current_user.id))


@router.get("/me/recommended-exercises", response_model=list[RecommendedExercise])
def get_recommended_exercises(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Gợi ý 3 loại bài theo profile bệnh (rule.md "Profile => Exercise Weight").

    aphasia_type của patient -> profile (broca_like/wernicke_like/mixed) -> trọng số 3 loại.
    CHỈ để hiển thị gợi ý (recommended = weight >= 0.3) — KHÔNG thay đổi logic giao bài
    (plan vẫn 10 bài/loại). Bác sĩ có thể điều chỉnh sau.
    """
    if current_user.role != UserRole.patient:
        raise HTTPException(
            status_code=403,
            detail="Chỉ bệnh nhân mới xem được gợi ý bài tập của mình",
        )

    patient = db.query(Patient).filter(Patient.id == current_user.id).first()
    profile = aphasia_type_to_profile(patient.aphasia_type if patient else None)
    weights = PROFILE_EXERCISE_WEIGHTS[profile]

    return [
        RecommendedExercise(
            exercise_type=exercise_type,
            display_name=EXERCISE_TYPE_DISPLAY_NAME[exercise_type],
            weight=weight,
            recommended=weight >= 0.3,
        )
        for exercise_type, weight in weights.items()
    ]
