"""
Router: sessions — PHIÊN TẬP theo rule.md mục 3 (1 phiên = 10 bài, mode + topic).

TẦNG MỚI ADDITIVE bao ngoài luồng làm bài hiện có:
  - ExerciseSession/SessionResult/scoring/TopicProgress GIỮ NGUYÊN 100%.
  - Bài được gắn vào phiên qua exercise_sessions.therapy_session_id (nullable) — submit
    KHÔNG kèm therapy_session_id (luồng cũ) chạy y như trước.
  - completed_count / total_retry_count TÍNH LẠI TỪ DB mỗi lần cần (single source,
    idempotent — không tăng dần thủ công nên không bao giờ lệch).
"""

from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.content import Exercise
from app.models.enums import ExerciseType, PlanStatus, SessionStatus, Topic, UserRole
from app.models.therapy import (
    ExerciseAssignment,
    ExerciseSession,
    SessionResult,
    TherapyPlan,
    TopicProgress,
)
from app.models.therapy_session import TherapySession
from app.models.user import User
from app.routers.auth import get_current_user
from app.routers.plans import _graded_assignment_ids
from app.schemas.content import AssignmentListItem
from app.schemas.therapy_session import (
    SessionStartRequest,
    SessionStartResponse,
    SessionStateResponse,
)
from app.services.plan_service import aphasia_type_to_profile

router = APIRouter(prefix="/sessions", tags=["sessions"])

PLANNED_COUNT = 10  # rule.md mục 3: mỗi phiên 10 bài


def _require_patient(current_user: User) -> None:
    if current_user.role != UserRole.patient:
        raise HTTPException(status_code=403, detail="Chỉ bệnh nhân mới dùng được phiên tập")


def _get_own_session(
    db: Session, session_id: uuid.UUID, current_user: User
) -> TherapySession:
    """Phiên CỦA CHÍNH patient đang đăng nhập; không có/của người khác -> 404."""
    ts = (
        db.query(TherapySession)
        .filter(TherapySession.id == session_id, TherapySession.patient_id == current_user.id)
        .first()
    )
    if ts is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên tập")
    return ts


def compute_session_counters(db: Session, therapy_session_id: uuid.UUID) -> tuple[int, int]:
    """
    (completed_count, total_retry_count) tính lại từ các ExerciseSession đã gắn vào phiên:
      - completed = số bài đã KẾT THÚC (status graded).
      - retry     = tổng (số SessionResult - 1) mỗi bài (lượt làm THÊM sau lượt đầu).
    """
    sessions = (
        db.query(ExerciseSession)
        .filter(ExerciseSession.therapy_session_id == therapy_session_id)
        .all()
    )
    completed = sum(1 for s in sessions if s.status == SessionStatus.graded)
    retry = 0
    for s in sessions:
        n = db.query(SessionResult).filter(SessionResult.session_id == s.id).count()
        retry += max(0, n - 1)
    return completed, retry


def _state_response(ts: TherapySession) -> SessionStateResponse:
    return SessionStateResponse(
        session_id=str(ts.id),
        status=ts.status,  # type: ignore[arg-type]
        mode=ts.mode,  # type: ignore[arg-type]
        topic=ts.topic,
        vocab_level=ts.vocab_level,
        profile=ts.profile,
        planned_count=ts.planned_count,
        completed_count=ts.completed_count,
        total_retry_count=ts.total_retry_count,
        started_at=ts.started_at,
        ended_at=ts.ended_at,
        duration_seconds=ts.duration_seconds,
    )


# ── (a) Bắt đầu phiên: chọn mode + topic -> 10 bài ───────────────────────────
@router.post("/start", response_model=SessionStartResponse)
def start_session(
    payload: SessionStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Tạo phiên (rule.md: Select Mode -> Select Topic -> 10 exercises).
    - topic bỏ trống = Mixed Topics (trộn mọi chủ đề; vocab_level=None — level theo từng bài).
    - Chọn bài: từ plan active, đúng dạng/chủ đề, ƯU TIÊN bài CHƯA làm xong, lấy 10 bài.
      mode="mixed": trộn ĐỀU 3 dạng, seed ổn định trong ngày.
      TODO(Giai đoạn 3): áp weighted theo profile (PROFILE_EXERCISE_WEIGHTS: Broca 70/30/0...).
    """
    _require_patient(current_user)

    # Validate topic (nếu có)
    topic_enum: Topic | None = None
    if payload.topic is not None:
        try:
            topic_enum = Topic(payload.topic)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"topic không hợp lệ: {payload.topic!r} (hợp lệ: {[t.value for t in Topic]})",
            )

    plan = (
        db.query(TherapyPlan)
        .filter(
            TherapyPlan.patient_id == current_user.id,
            TherapyPlan.status == PlanStatus.active,
        )
        .order_by(TherapyPlan.created_at.desc())
        .first()
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="Chưa có kế hoạch trị liệu")

    # Lấy assignment đúng dạng/chủ đề (tái dùng đúng kiểu lọc của /plans/me/assignments)
    types = (
        list(ExerciseType) if payload.mode == "mixed" else [ExerciseType(payload.mode)]
    )
    q = (
        db.query(ExerciseAssignment, Exercise)
        .join(Exercise, ExerciseAssignment.exercise_id == Exercise.id)
        .filter(
            ExerciseAssignment.plan_id == plan.id,
            Exercise.exercise_type.in_(types),
        )
    )
    if topic_enum is not None:
        q = q.filter(Exercise.topic == topic_enum)
    rows = q.order_by(ExerciseAssignment.order_index).all()
    if not rows:
        raise HTTPException(status_code=409, detail="Không có bài nào cho lựa chọn này")

    graded_ids = _graded_assignment_ids(db, [a.id for a, _ in rows])

    # mode=mixed: trộn đều ổn-định-trong-ngày (cùng seed logic /plans/me/assignments).
    if payload.mode == "mixed":
        seed = f"{current_user.id}:{payload.topic or 'all'}:{date.today().isoformat()}"
        random.Random(seed).shuffle(rows)

    # Ưu tiên bài CHƯA làm xong, rồi mới tới bài đã xong -> lấy 10
    pending = [(a, e) for a, e in rows if a.id not in graded_ids]
    done = [(a, e) for a, e in rows if a.id in graded_ids]
    picked = (pending + done)[:PLANNED_COUNT]

    # vocab_level lúc bắt đầu: theo TopicProgress của topic; Mixed Topics -> None (per-bài)
    vocab_level: int | None = None
    if topic_enum is not None:
        progress = (
            db.query(TopicProgress)
            .filter(
                TopicProgress.patient_id == current_user.id,
                TopicProgress.topic == topic_enum,
            )
            .first()
        )
        vocab_level = progress.current_level if progress else 1

    ts = TherapySession(
        patient_id=current_user.id,
        mode=payload.mode,
        topic=payload.topic,
        vocab_level=vocab_level,
        profile=aphasia_type_to_profile(
            current_user.aphasia_type if hasattr(current_user, "aphasia_type") else None
        ),
        started_at=datetime.now(timezone.utc),
        status="in_progress",
        planned_count=PLANNED_COUNT,
    )
    db.add(ts)
    db.commit()
    db.refresh(ts)

    return SessionStartResponse(
        session_id=str(ts.id),
        mode=payload.mode,
        topic=payload.topic,
        vocab_level=vocab_level,
        profile=ts.profile,
        planned_count=ts.planned_count,
        exercises=[
            AssignmentListItem(
                assignment_id=str(a.id),
                exercise_id=str(e.id),
                exercise_type=e.exercise_type.value,
                topic=e.topic.value,
                order_index=a.order_index,
                status="completed" if a.id in graded_ids else "pending",
            )
            for a, e in picked
        ],
    )


# ── (b) Kết thúc phiên ────────────────────────────────────────────────────────
@router.post("/{session_id}/finish", response_model=SessionStateResponse)
def finish_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Kết thúc phiên: đủ planned_count bài graded -> "completed"; chưa đủ -> "stopped_early"
    (rule.md: session ends khi đủ 10 HOẶC bệnh nhân dừng sớm).
    duration_seconds = ended_at - started_at. Phiên đã kết thúc rồi -> 409.
    """
    _require_patient(current_user)
    ts = _get_own_session(db, session_id, current_user)
    if ts.status != "in_progress":
        raise HTTPException(status_code=409, detail="Phiên đã kết thúc")

    completed, retry = compute_session_counters(db, ts.id)
    now = datetime.now(timezone.utc)
    ts.completed_count = completed
    ts.total_retry_count = retry
    ts.ended_at = now
    ts.duration_seconds = max(0, int((now - ts.started_at).total_seconds()))
    ts.status = "completed" if completed >= ts.planned_count else "stopped_early"
    db.commit()
    db.refresh(ts)
    return _state_response(ts)


# ── (c) Trạng thái phiên ──────────────────────────────────────────────────────
@router.get("/{session_id}", response_model=SessionStateResponse)
def get_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trạng thái + tiến độ phiên (x/10). Phiên đang chạy: counters tính lại trực tiếp."""
    _require_patient(current_user)
    ts = _get_own_session(db, session_id, current_user)
    if ts.status == "in_progress":
        completed, retry = compute_session_counters(db, ts.id)
        ts.completed_count = completed
        ts.total_retry_count = retry
        db.commit()
        db.refresh(ts)
    return _state_response(ts)
