"""
Pydantic schemas cho kế hoạch trị liệu (plan) — trang chủ "bài tập hôm nay".
"""

from __future__ import annotations

from pydantic import BaseModel

# Map exercise_type -> tên hiển thị tiếng Việt (tên MỚI đã chốt, đồng bộ với frontend
# src/constants/exercises.ts):
#   naming                 -> "Gọi tên"
#   command_identification -> "Nghe và đoán"   (tên cũ "Lặp lại")
#   sentence_building      -> "Hoàn thành câu" (tên cũ "Tạo câu")
EXERCISE_TYPE_DISPLAY_NAME = {
    "naming": "Gọi tên",
    "command_identification": "Nghe và đoán",
    "sentence_building": "Hoàn thành câu",
}

# Map Topic enum -> tên hiển thị tiếng Việt (màn "Chọn chủ đề").
TOPIC_DISPLAY_NAME = {
    "daily_activity": "Hoạt động thường ngày",
    "food_drink": "Ăn uống",
    "household_item": "Vật dụng",
    "family": "Gia đình",
    "body_part": "Bộ phận cơ thể",
    "number": "Số đếm",
}


class TodayExerciseSummary(BaseModel):
    """Tổng hợp tiến độ của 1 nhóm bài (theo exercise_type) trong ngày."""

    exercise_type: str
    display_name: str
    total_assigned: int
    completed_count: int
    completion_percent: float


class TodayPlanResponse(BaseModel):
    """Response cho GET /plans/me/today."""

    plan_id: str
    exercises: list[TodayExerciseSummary]


class TopicSummary(BaseModel):
    """1 topic CÓ BÀI trong plan của patient (GET /plans/me/topics) + tiến độ."""

    topic: str                # enum value, vd "food_drink"
    topic_display: str        # tên tiếng Việt, vd "Ăn uống"
    total_count: int          # tổng số bài trong plan thuộc topic (đã lọc theo type nếu có)
    completed_count: int      # số bài đã có >=1 lượt làm KẾT THÚC (graded)
