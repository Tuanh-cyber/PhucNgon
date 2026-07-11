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
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.assessment import Assessment, AssessmentResult
from app.models.enums import (
    AssessmentStatus,
    AssessmentType,
    PlanStatus,
    SessionStatus,
    UserRole,
)
from app.models.therapy import ExerciseSession, TherapyPlan
from app.models.user import Patient, User
from app.routers.auth import get_current_user
from app.schemas.assessment import ProgressDashboardResponse
from app.schemas.therapist import (
    PatientStats3,
    AttentionPatient,
    ClaimPatientRequest,
    ClaimPatientResponse,
    DashboardSummaryResponse,
    InsightItem,
    PatientHeader,
    TherapistPatientDetailResponse,
    TherapistPatientItem,
    TherapistPatientListResponse,
)
from app.services.phone_service import normalize_phone
from app.services.stats_service import (
    _local_date,
    compute_daily_scores,
    compute_patient_stats,
    compute_progress_dashboard,
)

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
    Gán bệnh nhân (khớp theo SỐ ĐIỆN THOẠI đã chuẩn hóa — Mô hình A) vào bác sĩ đang
    đăng nhập + điền hồ sơ/baseline. 1 transaction. Rẽ 3 nhánh theo plan.therapist_id:
      NULL          -> gán tôi ("claimed")
      == tôi        -> idempotent, cập nhật info ("updated")
      == bác sĩ khác -> 409 (KHÔNG lộ tên bác sĩ kia)
    """
    _require_therapist(current_user)

    # Chuẩn hóa số bác sĩ nhập; không ra dạng hợp lệ -> 422 (nói rõ, không âm thầm 404).
    phone_norm = normalize_phone(payload.phone)
    if phone_norm is None:
        raise HTTPException(
            status_code=422,
            detail="Số điện thoại không hợp lệ (cần số VN 10-11 chữ số, vd 0912345678 hoặc +84912345678)",
        )

    # So khớp trên dạng ĐÃ CHUẨN HÓA cả 2 phía (DB đang lưu chuỗi thô đủ kiểu định dạng).
    # TODO(tối ưu): đang normalize từng dòng trong Python — chấp nhận cho demo (ít bệnh
    # nhân); dữ liệu lớn thì thêm cột phone_normalized có index, backfill 1 lần.
    candidates = db.query(Patient).filter(Patient.phone_number.isnot(None)).all()
    matches = [p for p in candidates if normalize_phone(p.phone_number) == phone_norm]

    if len(matches) == 0:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy bệnh nhân với số này (bệnh nhân cần đăng ký kèm SĐT trước)",
        )
    if len(matches) > 1:
        raise HTTPException(
            status_code=409, detail="Nhiều bệnh nhân trùng số, cần xác định thêm"
        )
    patient = matches[0]

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


# ── Helpers số liệu per-patient (13.2/13.3/13.4) ─────────────────────────────
# ĐỊNH NGHĨA CHỐT (Bước 13.2):
#   - "Đang luyện tập": có >=1 buổi GRADED trong 7 ngày qua.
#   - "Cần chú ý"     : KHÔNG có buổi GRADED nào trong 3 ngày qua.
#   - "Buổi/tuần"     : số NGÀY có luyện trong 7 NGÀY GẦN NHẤT (rolling — khớp cách app
#                       bệnh nhân đang hiển thị "Mục tiêu tuần" từ daily_scores; KHÔNG phải
#                       tuần lịch T2-CN).
#   - progress_week   : completion CẤP PLAN có sẵn (% assignment đã graded trên toàn plan —
#                       code CHƯA có khái niệm "hoàn thành theo tuần"; dùng số có sẵn, đổi
#                       định nghĩa sau nếu team chốt khác).

ATTENTION_WINDOW_DAYS = 3   # 0 buổi graded trong N ngày -> "attention"
PRACTICING_WINDOW_DAYS = 7  # >=1 buổi graded trong N ngày -> "đang luyện tập"
INSIGHT_THRESHOLD = 60.0    # metric dưới ngưỡng này -> câu nhận xét "warn"


def _graded_days(db: Session, patient_id: uuid.UUID) -> set[date]:
    """Các NGÀY (giờ địa phương) có >=1 buổi graded — cùng cơ sở với streak của dashboard."""
    rows = (
        db.query(ExerciseSession.completed_at)
        .filter(
            ExerciseSession.patient_id == patient_id,
            ExerciseSession.status == SessionStatus.graded,
            ExerciseSession.completed_at.isnot(None),
        )
        .all()
    )
    return {_local_date(r[0]) for r in rows}


def _has_graded_within(graded_days: set[date], days: int) -> bool:
    today = date.today()
    return any(today - timedelta(days=days - 1) <= d <= today for d in graded_days)


def _avg_of_daily(daily_scores: list[dict]) -> float | None:
    """TB các avg_score khác None trong 1 dải daily_scores; cả dải trống -> None."""
    vals = [d["avg_score"] for d in daily_scores if d["avg_score"] is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _enrich_patient(db: Session, p: Patient) -> TherapistPatientItem:
    """
    Dựng 1 dòng bảng 13.2 — TÁI DÙNG compute_progress_dashboard + compute_patient_stats.
    TODO(tối ưu): đang tính per-patient trong loop (mỗi bệnh nhân vài query) — chấp nhận
    cho demo (<vài chục bệnh nhân/bác sĩ); khi dữ liệu lớn chuyển sang batch query
    (GROUP BY patient_id trên sessions/results) trong 1-2 câu SQL.
    """
    dash = compute_progress_dashboard(db, p.id)
    stats = compute_patient_stats(db, p.id)
    graded = _graded_days(db, p.id)

    return TherapistPatientItem(
        patient_id=str(p.id),
        full_name=p.full_name,
        email=p.email,
        aphasia_type=p.aphasia_type,
        severity_level=p.severity_level,
        hospital_name=p.hospital_name,
        progress_week=stats["completion_score"],
        avg_score_2days=_avg_of_daily(dash["daily_scores"][-2:]),
        streak_days=dash["streak"]["current_streak_days"],
        sessions_per_week=sum(1 for d in dash["daily_scores"] if d["session_count"] > 0),
        status=(
            "good" if _has_graded_within(graded, ATTENTION_WINDOW_DAYS) else "attention"
        ),
    )


def _my_patients(db: Session, therapist_id: uuid.UUID) -> list[Patient]:
    """Tập bệnh nhân của bác sĩ — CHỈ so sánh DƯƠNG therapist_id == me."""
    return (
        db.query(Patient)
        .join(TherapyPlan, TherapyPlan.patient_id == Patient.id)
        .filter(
            TherapyPlan.status == PlanStatus.active,
            TherapyPlan.therapist_id == therapist_id,  # so sánh DƯƠNG duy nhất
        )
        .order_by(Patient.full_name)
        .all()
    )


# ── (b) 13.2: Bảng bệnh nhân CỦA TÔI (filter + search + phân trang) ───────────
@router.get("/me/patients", response_model=TherapistPatientListResponse)
def list_my_patients(
    severity: str | None = None,
    aphasia_type: str | None = None,
    status: str | None = None,   # "good" | "attention"
    search: str | None = None,   # tìm theo tên (không phân biệt hoa thường)
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Bảng bệnh nhân của bác sĩ đăng nhập (mockup Ảnh 1). total = tổng SAU filter.
    status là cột DẪN XUẤT (tính từ hoạt động) -> lọc sau khi enrich; các filter còn lại
    lọc ngay trong SQL. Tất cả trên tập therapist_id == me.
    """
    _require_therapist(current_user)
    if status is not None and status not in ("good", "attention"):
        raise HTTPException(status_code=422, detail="status phải là 'good' hoặc 'attention'")

    patients = _my_patients(db, current_user.id)

    # Filter thuộc tính hồ sơ (đơn giản, tập nhỏ -> lọc python; TODO chuyển vào SQL khi lớn)
    if severity is not None:
        patients = [p for p in patients if p.severity_level == severity]
    if aphasia_type is not None:
        patients = [p for p in patients if p.aphasia_type == aphasia_type]
    if search:
        needle = search.strip().lower()
        patients = [p for p in patients if needle in p.full_name.lower()]

    items = [_enrich_patient(db, p) for p in patients]
    if status is not None:
        items = [it for it in items if it.status == status]

    return TherapistPatientListResponse(
        total=len(items),
        items=items[offset : offset + limit],
    )


# ── 13.3: 4 thẻ + banner dashboard ────────────────────────────────────────────
@router.get("/dashboard-summary", response_model=DashboardSummaryResponse)
def dashboard_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """4 thẻ tổng quan + banner 'N bệnh nhân chưa luyện 3 ngày' — tính TRÊN TẬP của tôi."""
    _require_therapist(current_user)
    patients = _my_patients(db, current_user.id)

    practicing = 0
    attention: list[AttentionPatient] = []
    completions: list[float] = []

    for p in patients:
        graded = _graded_days(db, p.id)
        if _has_graded_within(graded, PRACTICING_WINDOW_DAYS):
            practicing += 1
        if not _has_graded_within(graded, ATTENTION_WINDOW_DAYS):
            attention.append(AttentionPatient(patient_id=str(p.id), full_name=p.full_name))
        completion = compute_patient_stats(db, p.id)["completion_score"]
        if completion is not None:
            completions.append(completion)

    return DashboardSummaryResponse(
        total_patients=len(patients),
        practicing=practicing,
        need_attention=len(attention),
        weekly_completion=(
            round(sum(completions) / len(completions), 1) if completions else None
        ),
        attention_list=attention,
    )


# ── 13.4: Chi tiết 1 bệnh nhân (Ảnh 2) ────────────────────────────────────────
def _build_insight(stats: dict) -> InsightItem:
    """1 câu rule-based: chọn tiêu chí YẾU NHẤT dưới ngưỡng 60; cả 3 ổn -> ok."""
    texts = {
        "fluency_score": "Fluency thấp – bệnh nhân nói đúng nhưng còn chậm. Cân nhắc bài luyện tốc độ.",
        "accuracy_score": "Độ chính xác thấp – cân nhắc luyện phát âm/từ vựng cơ bản.",
        "completion_score": "Hoàn thành thấp – bệnh nhân bỏ dở nhiều, cân nhắc giảm độ khó.",
    }
    below = {
        k: v for k, v in stats.items() if v is not None and v < INSIGHT_THRESHOLD and k in texts
    }
    if below:
        weakest = min(below, key=below.get)  # tiêu chí YẾU NHẤT
        return InsightItem(type="warn", text=texts[weakest])
    if all(stats.get(k) is None for k in texts):
        return InsightItem(
            type="ok", text="Chưa đủ dữ liệu để nhận xét – bệnh nhân cần luyện tập thêm."
        )
    return InsightItem(type="ok", text="Tiến triển tốt – duy trì kế hoạch hiện tại.")


def _age_from_dob(dob: date) -> int:
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


@router.get("/patients/{patient_id}", response_model=TherapistPatientDetailResponse)
def get_patient_detail(
    patient: Patient = Depends(get_owned_patient),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Chi tiết 1 bệnh nhân CỦA TÔI (Ảnh 2) — mask get_owned_patient là lớp phân quyền duy nhất;
    số liệu TÁI DÙNG nguyên compute_progress_dashboard / compute_daily_scores /
    compute_patient_stats, KHÔNG viết lại.
    """
    dash = compute_progress_dashboard(db, patient.id)
    stats = compute_patient_stats(db, patient.id)

    # Delta tuần: 14 ngày -> cửa sổ [0:7] = tuần trước, [7:14] = 7 ngày gần nhất.
    days14 = compute_daily_scores(db, patient.id, days=14)
    prev_avg = _avg_of_daily(days14[:7])
    this_avg = _avg_of_daily(days14[7:])
    delta = (
        round(this_avg - prev_avg, 1) if prev_avg is not None and this_avg is not None else None
    )

    return TherapistPatientDetailResponse(
        patient=PatientHeader(
            full_name=patient.full_name,
            age=_age_from_dob(patient.date_of_birth),
            aphasia_type=patient.aphasia_type,
            severity_level=patient.severity_level,
            hospital_name=patient.hospital_name,
            doctor_name=current_user.full_name,
        ),
        dashboard=ProgressDashboardResponse(**dash),
        stats=PatientStats3(**stats),  # 3 chỉ số thành phần — cùng nguồn với insight
        avg_score_day=_avg_of_daily(dash["daily_scores"]),
        sessions_per_week=sum(1 for d in dash["daily_scores"] if d["session_count"] > 0),
        score_delta_vs_last_week=delta,
        insight=_build_insight(stats),
    )
