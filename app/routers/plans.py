"""
Router: plans — kế hoạch trị liệu của bệnh nhân.

GET /plans/me/today: tổng hợp tiến độ "bài tập hôm nay" cho trang chủ bệnh nhân.
GET /plans/me/topics?type=...: các topic CÓ BÀI trong plan (màn "Chọn chủ đề").
GET /plans/me/assignments?type=...&topic=...: danh sách bài (màn chọn bài; type="mixed"
  trộn cả 3 dạng, thứ tự ổn định trong ngày).
"""

from __future__ import annotations

import random
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.content import Exercise
from app.models.enums import (
    ExerciseType,
    PlanStatus,
    ResultLabel,
    SessionStatus,
    Topic,
    UserRole,
)
from app.models.therapy import ExerciseAssignment, ExerciseSession, SessionResult, TherapyPlan
from app.models.user import User
from app.routers.auth import get_current_user
from app.schemas.content import AssignmentListItem
from app.schemas.plan import (
    EXERCISE_TYPE_DISPLAY_NAME,
    TOPIC_DISPLAY_NAME,
    TodayExerciseSummary,
    TodayPlanResponse,
    TopicSummary,
)

router = APIRouter(prefix="/plans", tags=["plans"])

# Giá trị đặc biệt của query param `type`: gộp cả 3 dạng bài (luồng "Trộn cả 3 dạng").
MIXED_TYPE = "mixed"

# 3 nhóm bài hiển thị trên trang chủ.
_DISPLAY_TYPES = (
    ExerciseType.naming,
    ExerciseType.command_identification,
    ExerciseType.sentence_building,
)

# ResultLabel được coi là "ĐẠT" cho mục đích tính tiến độ:
#   pass  (bài speech đạt ngưỡng) + correct (CMD recognition chọn đúng).
# QUYẾT ĐỊNH này có thể cần điều chỉnh sau (vd có tính "near" là đạt một phần không?).
_PASSING_RESULTS = (ResultLabel.pass_, ResultLabel.correct)


@router.get("/me/today", response_model=TodayPlanResponse)
def get_today_plan(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Tổng hợp tiến độ bài tập hôm nay của bệnh nhân đang đăng nhập."""
    if current_user.role != UserRole.patient:
        raise HTTPException(
            status_code=403,
            detail="Chỉ bệnh nhân mới xem được bài tập của mình",
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

    summaries: list[TodayExerciseSummary] = []
    for exercise_type in _DISPLAY_TYPES:
        # total_assigned: số assignment thuộc plan này có đúng loại (join qua Exercise)
        assignment_ids = [
            row[0]
            for row in db.query(ExerciseAssignment.id)
            .join(Exercise, ExerciseAssignment.exercise_id == Exercise.id)
            .filter(
                ExerciseAssignment.plan_id == plan.id,
                Exercise.exercise_type == exercise_type,
            )
            .all()
        ]
        total_assigned = len(assignment_ids)

        # completed_count: trong các assignment trên, bao nhiêu cái có >=1 session graded
        # kèm SessionResult "đạt".
        if assignment_ids:
            completed_count = (
                db.query(ExerciseSession.assignment_id)
                .join(SessionResult, SessionResult.session_id == ExerciseSession.id)
                .filter(
                    ExerciseSession.assignment_id.in_(assignment_ids),
                    ExerciseSession.status == SessionStatus.graded,
                    SessionResult.result.in_(_PASSING_RESULTS),
                )
                .distinct()
                .count()
            )
        else:
            completed_count = 0

        percent = round(completed_count / total_assigned * 100, 0) if total_assigned else 0.0

        summaries.append(
            TodayExerciseSummary(
                exercise_type=exercise_type.value,
                display_name=EXERCISE_TYPE_DISPLAY_NAME[exercise_type.value],
                total_assigned=total_assigned,
                completed_count=completed_count,
                completion_percent=percent,
            )
        )

    return TodayPlanResponse(plan_id=str(plan.id), exercises=summaries)


# ── Helpers dùng chung cho /me/topics và /me/assignments ─────────────────────

def _require_patient(current_user: User) -> None:
    if current_user.role != UserRole.patient:
        raise HTTPException(
            status_code=403, detail="Chỉ bệnh nhân mới xem được bài tập của mình"
        )


def _get_active_plan(db: Session, patient_id) -> TherapyPlan:
    plan = (
        db.query(TherapyPlan)
        .filter(
            TherapyPlan.patient_id == patient_id,
            TherapyPlan.status == PlanStatus.active,
        )
        .order_by(TherapyPlan.created_at.desc())
        .first()
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="Chưa có kế hoạch trị liệu")
    return plan


def _parse_type_filter(type: str | None) -> list[ExerciseType]:
    """type=None hoặc "mixed" -> cả 3 dạng; 1 dạng cụ thể -> [dạng đó]; khác -> 422."""
    if type is None or type == MIXED_TYPE:
        return list(_DISPLAY_TYPES)
    try:
        return [ExerciseType(type)]
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"exercise_type không hợp lệ: {type!r} "
            f"(hợp lệ: {[e.value for e in ExerciseType]} hoặc '{MIXED_TYPE}')",
        )


def _graded_assignment_ids(db: Session, assignment_ids: list) -> set:
    """Các assignment đã có >=1 session graded (1 query, tránh N+1)."""
    if not assignment_ids:
        return set()
    return {
        row[0]
        for row in db.query(ExerciseSession.assignment_id)
        .filter(
            ExerciseSession.assignment_id.in_(assignment_ids),
            ExerciseSession.status == SessionStatus.graded,
        )
        .distinct()
        .all()
    }


@router.get("/me/topics", response_model=list[TopicSummary])
def get_my_topics(
    type: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Các topic THẬT SỰ CÓ BÀI trong plan active của patient (màn "Chọn chủ đề").

    - type: 1 dạng cụ thể -> chỉ xét bài dạng đó; "mixed" hoặc bỏ trống -> cả 3 dạng.
    - Mỗi topic kèm total_count + completed_count (bài có >=1 session graded — cùng
      định nghĩa "completed" với /me/assignments).
    - Thứ tự trả về theo thứ tự khai báo enum Topic (ổn định giữa các lần gọi).
    """
    _require_patient(current_user)
    type_filter = _parse_type_filter(type)
    plan = _get_active_plan(db, current_user.id)

    rows = (
        db.query(ExerciseAssignment.id, Exercise.topic)
        .join(Exercise, ExerciseAssignment.exercise_id == Exercise.id)
        .filter(
            ExerciseAssignment.plan_id == plan.id,
            Exercise.exercise_type.in_(type_filter),
        )
        .all()
    )
    graded_ids = _graded_assignment_ids(db, [r[0] for r in rows])

    by_topic: dict[Topic, dict] = {}
    for assignment_id, topic in rows:
        agg = by_topic.setdefault(topic, {"total": 0, "completed": 0})
        agg["total"] += 1
        if assignment_id in graded_ids:
            agg["completed"] += 1

    return [
        TopicSummary(
            topic=topic.value,
            topic_display=TOPIC_DISPLAY_NAME[topic.value],
            total_count=by_topic[topic]["total"],
            completed_count=by_topic[topic]["completed"],
        )
        for topic in Topic          # duyệt theo thứ tự enum -> output ổn định
        if topic in by_topic        # chỉ topic THẬT SỰ có bài
    ]


@router.get("/me/assignments", response_model=list[AssignmentListItem])
def get_my_assignments(
    type: str,
    topic: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Danh sách bài CỤ THỂ của patient (màn "Danh sách bài").

    - type : 1 dạng cụ thể, hoặc "mixed" = cả 3 dạng TRỘN ngẫu nhiên thứ tự.
    - topic: lọc theo chủ đề (luồng mới luôn truyền; để trống = mọi topic, giữ
      tương thích ngược với màn chọn bài cũ).
    - status = "completed" nếu assignment có >=1 ExerciseSession graded, ngược lại
      "pending". (Khác /me/today: today chỉ đếm graded + KẾT QUẢ ĐẠT; ở đây "đã làm
      xong bài" là đủ — bài graded nhưng sai vẫn là đã hoàn thành lượt làm.)
    - Sắp xếp: dạng đơn theo order_index; "mixed" trộn bằng seed
      (patient_id + topic + ngày) -> cùng ngày refresh bao nhiêu lần thứ tự vẫn
      y nguyên, sang ngày mới đổi.
    """
    _require_patient(current_user)
    type_filter = _parse_type_filter(type)

    topic_filter: Topic | None = None
    if topic is not None:
        try:
            topic_filter = Topic(topic)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"topic không hợp lệ: {topic!r} "
                f"(hợp lệ: {[t.value for t in Topic]})",
            )

    plan = _get_active_plan(db, current_user.id)

    query = (
        db.query(ExerciseAssignment, Exercise)
        .join(Exercise, ExerciseAssignment.exercise_id == Exercise.id)
        .filter(
            ExerciseAssignment.plan_id == plan.id,
            Exercise.exercise_type.in_(type_filter),
        )
    )
    if topic_filter is not None:
        query = query.filter(Exercise.topic == topic_filter)
    rows = query.order_by(ExerciseAssignment.order_index).all()

    if type == MIXED_TYPE:
        # Trộn ổn-định-trong-ngày: seed cố định theo (patient, topic, ngày) để
        # refresh không đổi thứ tự nhưng mỗi ngày là 1 lượt trộn mới.
        seed = f"{current_user.id}:{topic or 'all'}:{date.today().isoformat()}"
        random.Random(seed).shuffle(rows)

    graded_ids = _graded_assignment_ids(db, [a.id for a, _ in rows])

    return [
        AssignmentListItem(
            assignment_id=str(a.id),
            exercise_id=str(ex.id),
            exercise_type=ex.exercise_type.value,
            topic=ex.topic.value,
            order_index=a.order_index,
            status="completed" if a.id in graded_ids else "pending",
        )
        for a, ex in rows
    ]
