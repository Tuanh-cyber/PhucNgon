"""
Pydantic schemas cho màn "Kết quả đánh giá ban đầu" + chỉ số tiến độ tính tự động.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class InitialAssessmentResponse(BaseModel):
    """
    Dữ liệu cho màn "Kết quả đánh giá ban đầu".

    4 field chẩn đoán lấy trực tiếp từ hồ sơ Patient; 3 field điểm số lấy từ Assessment/
    AssessmentResult gần nhất (do bác sĩ/người nhà nhập tay lúc đăng ký). Nếu chưa có
    assessment nào thì 3 field điểm số = None (KHÔNG phải lỗi).
    """

    aphasia_type: Optional[str]
    severity_level: Optional[str]
    hospital_name: Optional[str]
    referring_doctor_name: Optional[str]
    accuracy_score: Optional[float]
    completion_score: Optional[float]
    fluency_score: Optional[float]


class PatientStatsResponse(BaseModel):
    """
    3 chỉ số TÍNH TỰ ĐỘNG từ lịch sử làm bài thật (SessionResult) — nguồn compute_patient_stats().

    KHÁC với InitialAssessmentResponse (Bước 11, bác sĩ nhập tay lúc đăng ký, cố định).
    Mỗi field = None nghĩa là "chưa có dữ liệu để tính" (KHÔNG phải điểm 0).
    """

    accuracy_score: Optional[float]
    completion_score: Optional[float]
    fluency_score: Optional[float]


class PatientProfileResponse(BaseModel):
    """GET /patients/me/profile — hồ sơ hiển thị ở màn 'Tài khoản' (chỉ xem)."""

    full_name: str
    email: str
    phone_number: Optional[str]
    date_of_birth: str              # ISO YYYY-MM-DD
    gender: str                     # male | female | other
    severity_level: Optional[str]
    aphasia_type: Optional[str]
    hospital_name: Optional[str]


# ── Dashboard tiến trình (GET /patients/me/progress-dashboard) ────────────────
class DailyScore(BaseModel):
    """Điểm trung bình 1 ngày (biểu đồ đường 7 ngày). avg_score=None = ngày không tập."""

    date: str                       # YYYY-MM-DD
    avg_score: Optional[float]      # trung bình SessionResult.score trong ngày, None nếu không có
    session_count: int              # số lượt làm bài (SessionResult) trong ngày


class StreakInfo(BaseModel):
    """Chuỗi ngày luyện tập liên tiếp + lịch hoạt động 30 ngày."""

    current_streak_days: int            # số ngày LIÊN TIẾP gần nhất có luyện tập, tính tới hôm nay
    active_days_last_30: list[str]      # các ngày YYYY-MM-DD có luyện tập trong 30 ngày qua


class DifficultWord(BaseModel):
    """1 từ bệnh nhân hay sai (heuristic MVP — xem compute_progress_dashboard)."""

    word: str                # canonical_word của vocab mục tiêu
    attempts: int            # số lượt làm bài có từ này
    fail_count: int          # số lượt KHÔNG đạt (retry/incorrect/near)
    exercise_type: str       # dạng bài từ này xuất hiện


class ProgressDashboardResponse(BaseModel):
    """Response cho GET /patients/me/progress-dashboard — 3 nhóm dữ liệu dashboard."""

    daily_scores: list[DailyScore]          # đúng 7 phần tử (7 ngày gần nhất, cũ -> mới) — dùng biểu đồ đường + lịch chi tiết
    daily_scores_30: list[DailyScore]       # đúng 30 phần tử (30 ngày gần nhất, cũ -> mới) — dùng heat-map đầy đủ 30 ngày
    streak: StreakInfo
    difficult_words: list[DifficultWord]    # tối đa 10, sắp giảm dần fail_count; rỗng nếu chưa đủ dữ liệu
