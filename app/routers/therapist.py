"""
Router: therapist — web BÁC SĨ (Bước 13.1: móng phân quyền + claim + 2 endpoint đọc).

MÔ HÌNH: bác sĩ↔bệnh nhân link qua TherapyPlan.therapist_id của plan ACTIVE.
Bệnh nhân TỰ DO (therapist_id=NULL, tự đăng ký dùng một mình) là trạng thái HỢP LỆ —
không thuộc dashboard của bất kỳ bác sĩ nào.

NGUYÊN TẮC PHÂN QUYỀN (chống rò hồ sơ y tế):
  - get_owned_patient là NGUỒN DUY NHẤT quyết định bác sĩ có được xem 1 bệnh nhân không.
  - Mọi truy vấn phía bác sĩ CHỈ dùng so sánh DƯƠNG therapist_id == current_user.id.
    TUYỆT ĐỐI KHÔNG dùng so sánh âm (!=, NOT IN): trong SQL, NULL thoát khỏi mọi phép âm
    -> bệnh nhân tự do sẽ lọt vào tập của bác sĩ = rò hồ sơ.
  - Không sở hữu (của bác sĩ khác HOẶC tự do) -> 404 đồng nhất, không lộ "bệnh nhân tồn tại".
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.assessment import Assessment, AssessmentResult
from app.models.enums import AssessmentStatus, AssessmentType, PlanStatus, UserRole
from app.models.therapy import TherapyPlan
from app.models.user import Patient, User
from app.routers.auth import get_current_user
from app.schemas.assessment import ProgressDashboardResponse
from app.schemas.therapist import (
    ClaimPatientRequest,
    ClaimPatientResponse,
    TherapistPatientItem,
)
from app.services.stats_service import compute_progress_dashboard

router = APIRouter(prefix="/therapist", tags=["therapist"])


def _require_therapist(current_user: User) -> None:
    if current_user.role != UserRole.therapist:
        raise HTTPException(status_code=403, detail="Chỉ bác sĩ mới truy cập được")


def get_owned_patient(
    patient_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Patient:
    """
    Dependency mask — nguồn phân quyền DUY NHẤT cho endpoint chi tiết bệnh nhân.

    Trả Patient CHỈ KHI plan ACTIVE của bệnh nhân có therapist_id == current_user.id.
    3 trường hợp TƯỜNG MINH:
      1. Bệnh nhân của TÔI                   -> trả Patient (200)
      2. Bệnh nhân của bác sĩ KHÁC           -> 404
      3. Bệnh nhân TỰ DO (therapist_id=NULL) -> 404
    Chọn 404 (không phải 403) cho cả 2+3: không tiết lộ bệnh nhân này tồn tại.

    SQL NULL: chỉ so sánh DƯƠNG therapist_id == UUID cụ thể — NULL không bao giờ bằng
    một UUID nên bệnh nhân tự do tự động bị loại, không cần (và không được) thêm phép âm.
    """
    _require_therapist(current_user)

    owned = (
        db.query(TherapyPlan.id)
        .filter(
            TherapyPlan.patient_id == patient_id,
            TherapyPlan.status == PlanStatus.active,
            TherapyPlan.therapist_id == current_user.id,  # so sánh DƯƠNG duy nhất
        )
        .first()
    )
    if owned is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy bệnh nhân")

    return db.query(Patient).filter(Patient.id == patient_id).one()


# ── (a) Claim: bác sĩ NHẬN 1 bệnh nhân đã tự đăng ký ──────────────────────────
@router.post("/patients/claim", response_model=ClaimPatientResponse)
def claim_patient(
    payload: ClaimPatientRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Gán bệnh nhân (tra theo email) vào bác sĩ đang đăng nhập + điền hồ sơ/baseline.
    1 transaction. Rẽ 3 nhánh theo plan.therapist_id:
      NULL          -> gán tôi ("claimed")
      == tôi        -> idempotent, cập nhật info ("updated")
      == bác sĩ khác -> 409 (KHÔNG lộ tên bác sĩ kia)
    """
    _require_therapist(current_user)

    # Patient joined-inheritance: query Patient tự JOIN users -> lọc thẳng bằng email
    # kế thừa. Email của therapist/caregiver không nằm trong tập Patient -> None.
    patient = db.query(Patient).filter(Patient.email == payload.email).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy bệnh nhân với email này")

    plan = (
        db.query(TherapyPlan)
        .filter(
            TherapyPlan.patient_id == patient.id,
            TherapyPlan.status == PlanStatus.active,
        )
        .order_by(TherapyPlan.created_at.desc())
        .first()
    )
    if plan is None:
        raise HTTPException(status_code=409, detail="Bệnh nhân chưa có kế hoạch trị liệu")

    if plan.therapist_id is None:
        plan.therapist_id = current_user.id
        status = "claimed"
    elif plan.therapist_id == current_user.id:
        status = "updated"  # idempotent: gọi lại để cập nhật hồ sơ
    else:
        raise HTTPException(status_code=409, detail="Bệnh nhân đã thuộc bác sĩ khác")

    # Ghi các field CÓ GỬI vào hồ sơ Patient (không đè None lên dữ liệu cũ).
    if payload.aphasia_type is not None:
        patient.aphasia_type = payload.aphasia_type
    if payload.hospital_name is not None:
        patient.hospital_name = payload.hospital_name
    if payload.severity_level is not None:
        patient.severity_level = payload.severity_level

    # Baseline: >=1 điểm -> tạo Assessment + AssessmentResult (y nguyên logic register).
    if any(
        v is not None
        for v in (payload.accuracy_score, payload.completion_score, payload.fluency_score)
    ):
        now = datetime.now(timezone.utc)
        assessment = Assessment(
            patient_id=patient.id,
            type=AssessmentType.language,
            status=AssessmentStatus.completed,
            started_at=now,
            completed_at=now,
        )
        db.add(assessment)
        db.flush()
        db.add(
            AssessmentResult(
                assessment_id=assessment.id,
                accuracy_score=payload.accuracy_score,
                completion_score=payload.completion_score,
                fluency_score=payload.fluency_score,
            )
        )

    db.commit()
    return ClaimPatientResponse(
        patient_id=str(patient.id), full_name=patient.full_name, status=status
    )


# ── (b) Danh sách bệnh nhân CỦA TÔI ──────────────────────────────────────────
@router.get("/me/patients", response_model=list[TherapistPatientItem])
def list_my_patients(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Bệnh nhân thuộc bác sĩ đang đăng nhập — CHỈ filter therapist_id == me (so sánh dương).
    13.1 trả tối thiểu; cột chi tiết + filter/phân trang để 13.2.
    """
    _require_therapist(current_user)

    rows = (
        db.query(Patient)
        .join(TherapyPlan, TherapyPlan.patient_id == Patient.id)
        .filter(
            TherapyPlan.status == PlanStatus.active,
            TherapyPlan.therapist_id == current_user.id,  # so sánh DƯƠNG duy nhất
        )
        .order_by(Patient.full_name)
        .all()
    )
    return [
        TherapistPatientItem(
            patient_id=str(p.id),
            full_name=p.full_name,
            email=p.email,
            aphasia_type=p.aphasia_type,
            severity_level=p.severity_level,
            hospital_name=p.hospital_name,
        )
        for p in rows
    ]


# ── (c) Chi tiết 1 bệnh nhân: dashboard tiến trình ────────────────────────────
@router.get("/patients/{patient_id}", response_model=ProgressDashboardResponse)
def get_patient_detail(
    patient: Patient = Depends(get_owned_patient),
    db: Session = Depends(get_db),
):
    """
    Dashboard tiến trình của 1 bệnh nhân CỦA TÔI — tái dùng nguyên compute_progress_dashboard
    (đã dùng cho app bệnh nhân), mask get_owned_patient là lớp duy nhất thêm vào.
    """
    return ProgressDashboardResponse(**compute_progress_dashboard(db, patient.id))
