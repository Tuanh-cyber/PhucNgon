"""
PhụcNgôn — PLAN SERVICE (auto-provisioning kế hoạch trị liệu khởi đầu).

Khi 1 Patient tự đăng ký, hệ thống tự tạo 1 TherapyPlan "khởi đầu" và giao sẵn bài tập
theo độ nặng của bệnh (severity_level -> vocab_level), để bệnh nhân có thể làm bài ngay
mà không cần chờ therapist gán tay.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.content import Exercise
from app.models.enums import ExerciseType, PlanStatus
from app.models.therapy import ExerciseAssignment, TherapyPlan

# Số bài giao cho MỖI loại exercise_type trong plan khởi đầu.
EXERCISES_PER_TYPE = 10

# Map severity_level (text tự do trong hồ sơ bệnh) -> vocab_level bắt đầu.
# Nặng nhất -> level dễ nhất (1). Giá trị lạ -> mặc định 1 (an toàn nhất).
SEVERITY_TO_LEVEL = {
    "Nặng": 1,
    "Trung bình": 2,
    "Nhẹ": 3,
}
DEFAULT_VOCAB_LEVEL = 1

# ── Profile bệnh -> trọng số loại bài (rule.md "Profile => Exercise Weight") ──
# aphasia_type từ form đăng ký (3 lựa chọn: "Broca" / "Wernicke" / "Loại Aphasia khác")
# -> profile. Khớp SUBSTRING không phân biệt hoa thường để bao luôn dữ liệu cũ dạng tự do
# ("Aphasia Broca"...). Không nhận diện được / None -> mixed (trung tính nhất).
def aphasia_type_to_profile(aphasia_type: str | None) -> str:
    """Map aphasia_type (text) -> profile: broca_like | wernicke_like | mixed."""
    lowered = (aphasia_type or "").lower()
    if "broca" in lowered:
        return "broca_like"
    if "wernicke" in lowered:
        return "wernicke_like"
    return "mixed"


# Trọng số = tần suất gợi ý (KHÔNG phải điều kiện được/không được làm) — rule.md mục 1.
# Chỉ dùng để HIỂN THỊ gợi ý; logic giao bài thật vẫn 10 bài/loại, không đổi.
PROFILE_EXERCISE_WEIGHTS: dict[str, dict[str, float]] = {
    "broca_like": {
        "naming": 0.7, "command_identification": 0.3, "sentence_building": 0.0,
    },
    "wernicke_like": {
        "naming": 0.2, "command_identification": 0.5, "sentence_building": 0.3,
    },
    "mixed": {
        "naming": 0.3, "command_identification": 0.3, "sentence_building": 0.4,
    },
}


def _severity_to_level(severity_level: str | None) -> int:
    """Map severity_level -> vocab_level. Không khớp bảng -> DEFAULT_VOCAB_LEVEL (không raise)."""
    return SEVERITY_TO_LEVEL.get(severity_level or "", DEFAULT_VOCAB_LEVEL)


def _pick_exercises(
    db_session: Session,
    exercise_type: ExerciseType,
    vocab_level: int,
    k: int = EXERCISES_PER_TYPE,
    topic=None,
) -> list[Exercise]:
    """
    Chọn tối đa k Exercise ngẫu nhiên cho 1 exercise_type.

    topic (optional): giới hạn theo 1 topic cụ thể (dùng khi lên level — giao bài khó hơn
    CÙNG topic vừa luyện). None = mọi topic (plan khởi đầu).

    Ưu tiên:
      1. Đúng vocab_level yêu cầu (ngẫu nhiên).
      2. Nếu chưa đủ k, bù thêm từ vocab_level THẤP HƠN (gần nhất trước — level cao hơn trong
         nhóm thấp hơn), KHÔNG bao giờ lấy bài KHÓ HƠN khả năng hiện tại (giống nguyên tắc
         pick_distractors).
      3. Vẫn không đủ k -> trả về tất cả những gì có, KHÔNG raise (giao ít còn hơn giao khó).
    """
    topic_filters = [Exercise.topic == topic] if topic is not None else []

    # Tầng 1: đúng level, ngẫu nhiên
    chosen = (
        db_session.query(Exercise)
        .filter(
            Exercise.exercise_type == exercise_type,
            Exercise.vocab_level == vocab_level,
            *topic_filters,
        )
        .order_by(func.random())
        .limit(k)
        .all()
    )
    if len(chosen) >= k:
        return chosen

    # Tầng 2: bù từ level THẤP HƠN (gần nhất trước), loại các bài đã chọn
    remaining = k - len(chosen)
    chosen_ids = {e.id for e in chosen}
    filters = [
        Exercise.exercise_type == exercise_type,
        Exercise.vocab_level < vocab_level,
        *topic_filters,
    ]
    if chosen_ids:
        filters.append(Exercise.id.notin_(chosen_ids))

    backfill = (
        db_session.query(Exercise)
        .filter(*filters)
        .order_by(Exercise.vocab_level.desc(), func.random())
        .limit(remaining)
        .all()
    )
    return chosen + backfill


def add_level_up_assignments(
    db_session: Session,
    plan: TherapyPlan,
    exercise_type: ExerciseType,
    vocab_level: int,
    topic,
    k: int = EXERCISES_PER_TYPE,
) -> int:
    """
    Khi bệnh nhân LÊN LEVEL: append k assignment mới vào plan — cùng loại bài, cùng topic,
    ở vocab_level MỚI (khó hơn) — để lượt sau có bài thử thách hơn.

    Trả về số assignment đã thêm (có thể < k nếu ngân hàng bài không đủ; KHÔNG raise).
    KHÔNG commit — caller (submit_attempt) quyết định commit trong cùng transaction.
    """
    exercises = _pick_exercises(
        db_session, exercise_type, vocab_level, k=k, topic=topic
    )
    if not exercises:
        return 0

    # order_index tiếp nối sau assignment lớn nhất hiện có của plan.
    max_order = (
        db_session.query(func.coalesce(func.max(ExerciseAssignment.order_index), -1))
        .filter(ExerciseAssignment.plan_id == plan.id)
        .scalar()
    )
    order_index = (max_order if max_order is not None else -1) + 1
    for ex in exercises:
        db_session.add(
            ExerciseAssignment(plan_id=plan.id, exercise_id=ex.id, order_index=order_index)
        )
        order_index += 1

    db_session.flush()
    return len(exercises)


def create_initial_plan(db_session: Session, patient) -> TherapyPlan:
    """
    Tạo 1 TherapyPlan khởi đầu cho patient + giao bài (EXERCISES_PER_TYPE mỗi loại).

    - therapist_id = None (patient tự đăng ký, chưa có therapist nhận ca).
    - status = active, start_date = hôm nay.
    - flush() để lấy UUID; caller quyết định commit/rollback.
    """
    vocab_level = _severity_to_level(patient.severity_level)

    plan = TherapyPlan(
        patient_id=patient.id,
        therapist_id=None,
        title="Kế hoạch khởi đầu",
        status=PlanStatus.active,
        start_date=date.today(),
    )
    db_session.add(plan)
    db_session.flush()  # cần plan.id để gắn assignment

    order_index = 0
    for exercise_type in (
        ExerciseType.naming,
        ExerciseType.command_identification,
        ExerciseType.sentence_building,
    ):
        exercises = _pick_exercises(db_session, exercise_type, vocab_level)
        for ex in exercises:
            db_session.add(
                ExerciseAssignment(
                    plan_id=plan.id,
                    exercise_id=ex.id,
                    order_index=order_index,
                )
            )
            order_index += 1

    db_session.flush()
    return plan
