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


def _start_logic_sequence_session(db: Session, current_user: User) -> SessionStartResponse:
    """Phiên logic_sequence: 10/13 bài sắp xếp, trộn seed ổn định trong ngày, mọi level."""
    from app.models.sequence import LogicSequenceExercise  # import cục bộ: tránh vòng

    bank = db.query(LogicSequenceExercise).order_by(LogicSequenceExercise.exercise_code).all()
    if not bank:
        raise HTTPException(status_code=409, detail="Chưa có bài sắp xếp nào (chưa seed)")

    seed = f"{current_user.id}:logic_sequence:{date.today().isoformat()}"
    random.Random(seed).shuffle(bank)

    # Ưu tiên bài CHƯA hoàn thành (chưa có ExerciseSession graded của bài đó)
    done_ids = {
        row[0]
        for row in db.query(ExerciseSession.logic_sequence_exercise_id)
        .filter(
            ExerciseSession.patient_id == current_user.id,
            ExerciseSession.logic_sequence_exercise_id.isnot(None),
            ExerciseSession.status == SessionStatus.graded,
        )
        .distinct()
        .all()
    }
    ordered = [e for e in bank if e.id not in done_ids] + [e for e in bank if e.id in done_ids]
    picked = ordered[:PLANNED_COUNT]  # 13 >= 10 -> đủ; nếu ít hơn lấy tối đa

    ts = TherapySession(
        patient_id=current_user.id,
        mode="logic_sequence",
        topic=None,                 # không áp dụng topic
        vocab_level=None,           # không áp dụng level (leveling ngủ đông)
        profile=aphasia_type_to_profile(getattr(current_user, "aphasia_type", None)),
        started_at=datetime.now(timezone.utc),
        status="in_progress",
        planned_count=PLANNED_COUNT,
    )
    db.add(ts)
    db.commit()
    db.refresh(ts)

    return SessionStartResponse(
        session_id=str(ts.id),
        mode="logic_sequence",
        topic=None,
        vocab_level=None,
        profile=ts.profile,
        planned_count=ts.planned_count,
        exercises=[
            AssignmentListItem(
                assignment_id=str(e.id),  # không có assignment — set trùng exercise_id
                exercise_id=str(e.id),
                exercise_type="logic_sequence",
                topic="",
                order_index=i,
                status="completed" if e.id in done_ids else "pending",
                exercise_kind="logic_sequence",
            )
            for i, e in enumerate(picked)
        ],
    )


def _start_color_recognition_session(db: Session, current_user: User) -> SessionStartResponse:
    """Phiên color_recognition: 10/12 bài chọn màu — cùng khuôn logic_sequence
    (không topic, không level, seed ổn định trong ngày, ưu tiên bài chưa hoàn thành).
    exercises[].exercise_id = exercise_code ("CLR...") để FE gọi /color-recognition/{code}."""
    from app.models.color_recognition import ColorRecognitionExercise  # import cục bộ

    bank = (
        db.query(ColorRecognitionExercise)
        .order_by(ColorRecognitionExercise.exercise_code)
        .all()
    )
    if not bank:
        raise HTTPException(status_code=409, detail="Chưa có bài nhận biết màu nào (chưa seed)")

    seed = f"{current_user.id}:color_recognition:{date.today().isoformat()}"
    random.Random(seed).shuffle(bank)

    done_ids = {
        row[0]
        for row in db.query(ExerciseSession.color_recognition_exercise_id)
        .filter(
            ExerciseSession.patient_id == current_user.id,
            ExerciseSession.color_recognition_exercise_id.isnot(None),
            ExerciseSession.status == SessionStatus.graded,
        )
        .distinct()
        .all()
    }
    ordered = [e for e in bank if e.id not in done_ids] + [e for e in bank if e.id in done_ids]
    picked = ordered[:PLANNED_COUNT]  # 12 >= 10 -> đủ

    ts = TherapySession(
        patient_id=current_user.id,
        mode="color_recognition",
        topic=None,
        vocab_level=None,
        profile=aphasia_type_to_profile(getattr(current_user, "aphasia_type", None)),
        started_at=datetime.now(timezone.utc),
        status="in_progress",
        planned_count=PLANNED_COUNT,
    )
    db.add(ts)
    db.commit()
    db.refresh(ts)

    return SessionStartResponse(
        session_id=str(ts.id),
        mode="color_recognition",
        topic=None,
        vocab_level=None,
        profile=ts.profile,
        planned_count=ts.planned_count,
        exercises=[
            AssignmentListItem(
                assignment_id=e.exercise_code,  # không có assignment — trùng exercise_code
                exercise_id=e.exercise_code,    # FE gọi /color-recognition/{code}
                exercise_type="color_recognition",
                topic="",
                order_index=i,
                status="completed" if e.id in done_ids else "pending",
                exercise_kind="color_recognition",
            )
            for i, e in enumerate(picked)
        ],
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
    - topic bỏ trống = Mixed Topics (trộn mọi chủ đề).
    - CHỌN BÀI TỪ NGÂN HÀNG Exercise (mọi vocab_level — KHÔNG lọc level: nâng level đang
      NGỦ ĐÔNG vì vocab theo level quá thưa, xem LEVELING_ENABLED ở session_service).
      Bài nào chưa có trong plan -> tự tạo ExerciseAssignment (get-or-create) để luồng
      submit giữ nguyên (vẫn assignment-based).
    - Ưu tiên bài CHƯA làm xong; trộn ổn định trong ngày; <10 bài khả dụng -> lấy tối đa
      (không lặp bài, không lỗi — mỗi topic ~15 vocab nên thực tế đủ 10).
      TODO(Giai đoạn 3): mode="mixed" áp weighted theo profile (Broca 70/30/0...).
    """
    _require_patient(current_user)

    # ── MODE logic_sequence: modality riêng — KHÔNG topic, KHÔNG assignment/plan ──
    # Chọn 10 từ 13 bài sắp xếp (trộn mọi level — leveling ngủ đông), seed ổn định
    # trong ngày. exercises[] trả exercise_kind="logic_sequence" để FE render màn
    # kéo-thả; FE gọi GET/POST /logic-sequence/{exercise_id}.
    if payload.mode == "logic_sequence":
        return _start_logic_sequence_session(db, current_user)
    if payload.mode == "color_recognition":
        return _start_color_recognition_session(db, current_user)

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

    # ── Chọn bài từ NGÂN HÀNG (mọi level) ──
    types = (
        list(ExerciseType) if payload.mode == "mixed" else [ExerciseType(payload.mode)]
    )
    q = db.query(Exercise).filter(
        Exercise.exercise_type.in_(types), Exercise.is_active.is_(True)
    )
    if topic_enum is not None:
        q = q.filter(Exercise.topic == topic_enum)
    bank = q.order_by(Exercise.exercise_code).all()
    if not bank:
        raise HTTPException(status_code=409, detail="Không có bài nào cho lựa chọn này")

    # Trộn ổn-định-trong-ngày (mọi mode — thứ tự bank vốn không có ý nghĩa với bệnh nhân)
    seed = f"{current_user.id}:{payload.mode}:{payload.topic or 'all'}:{date.today().isoformat()}"
    random.Random(seed).shuffle(bank)

    # Assignment hiện có của plan cho các exercise này (để get-or-create + biết bài đã xong)
    existing = {
        a.exercise_id: a
        for a in db.query(ExerciseAssignment)
        .filter(
            ExerciseAssignment.plan_id == plan.id,
            ExerciseAssignment.exercise_id.in_([e.id for e in bank]),
        )
        .all()
    }
    graded_ids = _graded_assignment_ids(
        db, [a.id for a in existing.values()]
    )

    def _is_done(e: Exercise) -> bool:
        a = existing.get(e.id)
        return a is not None and a.id in graded_ids

    # Ưu tiên bài CHƯA làm xong; <10 -> lấy tối đa có thể (KHÔNG lặp bài)
    ordered = [e for e in bank if not _is_done(e)] + [e for e in bank if _is_done(e)]
    picked_exercises = ordered[:PLANNED_COUNT]

    # get-or-create ExerciseAssignment cho bài chưa có trong plan
    next_index = (
        db.query(ExerciseAssignment)
        .filter(ExerciseAssignment.plan_id == plan.id)
        .count()
    )
    picked: list[tuple[ExerciseAssignment, Exercise]] = []
    for e in picked_exercises:
        a = existing.get(e.id)
        if a is None:
            a = ExerciseAssignment(plan_id=plan.id, exercise_id=e.id, order_index=next_index)
            next_index += 1
            db.add(a)
            db.flush()
        picked.append((a, e))

    # vocab_level: KHÔNG còn dùng để lọc (nâng level ngủ đông) -> luôn None.
    # Giữ cột để bật lại sau; TopicProgress không bị đọc ở đây nữa.
    vocab_level: int | None = None

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
