"""
PhụcNgôn — STATS SERVICE (chỉ số TÍNH TỰ ĐỘNG từ lịch sử làm bài thật).

compute_patient_stats() tổng hợp 3 chỉ số "Độ chính xác / Hoàn thành / Trôi chảy" từ dữ liệu
SessionResult THẬT trên TherapyPlan đang active của bệnh nhân.

QUAN TRỌNG — phân biệt 2 nguồn dữ liệu ĐỘC LẬP, KHÔNG gộp:
  - stats_service (file này)  : TÍNH TỰ ĐỘNG từ lịch sử làm bài (SessionResult). Thay đổi theo
                                thời gian khi bệnh nhân luyện tập.
  - AssessmentResult (Bước 11): bác sĩ NHẬP TAY lúc đăng ký, cố định. KHÔNG đụng ở đây.

Đây là hàm DÙNG CHUNG: mọi nơi cần 3 chỉ số này (màn kết quả bài tập, dashboard bác sĩ ở
Module 9 sau này) PHẢI gọi đúng compute_patient_stats(), KHÔNG viết lại công thức nơi khác.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.content import Exercise
from app.models.enums import ExerciseType, PlanStatus, ResultLabel, SessionStatus
from app.models.therapy import (
    ExerciseAssignment,
    ExerciseSession,
    SessionResult,
    TherapyPlan,
)


def _round1(value: Optional[float]) -> Optional[float]:
    """Làm tròn 1 chữ số thập phân, giữ None nguyên (None = 'chưa có dữ liệu')."""
    return None if value is None else round(value, 1)


def round_metric(value: Optional[float]) -> Optional[float]:
    """Bản public của _round1 — cho router/màn kết quả làm tròn 3 tiêu chí đồng nhất."""
    return _round1(value)


def attempt_to_metrics(
    score: Optional[float],
    components: Optional[dict],
    result: str,
) -> dict:
    """
    Map dữ liệu 1 LƯỢT làm bài (score + components + result) -> 3 tiêu chí RIÊNG lượt đó.
    CHỈ response submit (màn Kết quả bài tập) dùng các giá trị này.

    Quan hệ "field nào -> tiêu chí nào":
      - accuracy_score   = score của lượt. None khi bài KHÔNG cho điểm liên tục:
                           CMD recognition (touch, chỉ Đúng/Sai) hoặc input "invalid".
      - fluency_score    = components["fluency"]. None khi không có key này:
                           recognition (components={"binary_touch":...}) hoặc
                           invalid (components={"error":...}).
      - completion_score = ĐỘ PHỦ NỘI DUNG (recall phần cần nói) của LƯỢT NÀY, suy từ
                           components theo thứ tự ưu tiên:
                             * "keyword_coverage" nếu có (dự phòng nếu SEN tách key riêng)
                               -> điểm lẻ.
                             * elif "keyword" (thực tế cả SEN lẫn NAM/CMD-repetition đều
                               lưu ở key này): SEN -> keyword_coverage() (điểm lẻ, vd
                               2/3 -> 66.67); NAM/CMD-repetition -> keyword_match() (0/100,
                               "có gọi đúng tên không").
                             * elif recognition (binary_touch / result correct|incorrect)
                               -> 100.0 nếu "correct" else 0.0 (chọn đúng ô = phủ đủ).
                             * else (invalid, components={"error":...}) -> None (không đo được).

    ⚠ completion_score Ở ĐÂY (cấp-1-lượt = "độ phủ nội dung / recall") KHÁC HẲN
    completion_score trong compute_patient_stats (cấp-plan = "tiến độ chương trình",
    tức thẻ "Hoàn thành tuần" trên dashboard = số assignment đã graded / tổng). Hai khái
    niệm CỐ Ý khác nhau. compute_patient_stats KHÔNG gọi completion từ hàm này (nó chỉ lấy
    accuracy_score & fluency_score), nên thay đổi ở đây không lan sang dashboard.

    Trả GIÁ TRỊ THÔ (chưa làm tròn) — caller tự làm tròn khi hiển thị (round_metric).
    """
    comp = components if isinstance(components, dict) else {}
    fluency = comp.get("fluency")

    if "keyword_coverage" in comp:
        completion: Optional[float] = comp["keyword_coverage"]
    elif "keyword" in comp:
        completion = comp["keyword"]
    elif "binary_touch" in comp or result in ("correct", "incorrect"):
        completion = 100.0 if result == "correct" else 0.0
    else:
        completion = None  # invalid / input rác -> không đo được độ phủ

    return {
        "accuracy_score": score,
        "completion_score": completion,
        "fluency_score": fluency,
    }


def compute_patient_stats(db_session: Session, patient_id: uuid.UUID) -> dict:
    """
    Tổng hợp 3 chỉ số từ SessionResult THẬT, tính trên TherapyPlan đang active của patient.

    Trả về:
      { "accuracy_score": float | None,
        "completion_score": float | None,
        "fluency_score": float | None }

    Trả None cho từng chỉ số khi CHƯA đủ dữ liệu để tính (KHÔNG trả 0 — 0 gây hiểu lầm là điểm
    kém, còn None nghĩa là "chưa có dữ liệu").

    QUYẾT ĐỊNH tính toán (đã đối chiếu scoring_service.py):
      - accuracy_score = trung bình cột SessionResult.score của MỌI result CÓ score.
        `score` là None ở 2 trường hợp (theo score() trong scoring_service): bài
        command_identification/recognition (chỉ có is_correct, không có điểm liên tục) và
        input bị loại ("invalid"). Ta BỎ QUA các dòng score=None — KHÔNG tính là 0.
      - completion_score = (số ExerciseAssignment có >=1 session status="graded") / tổng số
        assignment của plan * 100.
      - fluency_score = trung bình components["fluency"] của các result CÓ key này. Key
        "fluency" có mặt ở naming/command_repetition/sentence_building hợp lệ; KHÔNG có ở
        recognition (components={"binary_touch":...}) và invalid (components={"error":...}).
        Bỏ qua dòng không có key — KHÔNG tính là 0.
    """
    empty = {"accuracy_score": None, "completion_score": None, "fluency_score": None}

    # 1. Plan active mới nhất của patient. Không có -> cả 3 None.
    plan = (
        db_session.query(TherapyPlan)
        .filter(
            TherapyPlan.patient_id == patient_id,
            TherapyPlan.status == PlanStatus.active,
        )
        .order_by(TherapyPlan.created_at.desc())
        .first()
    )
    if plan is None:
        return empty

    # 2. Tất cả assignment của plan.
    assignment_ids = [
        row[0]
        for row in db_session.query(ExerciseAssignment.id)
        .filter(ExerciseAssignment.plan_id == plan.id)
        .all()
    ]
    total_assignments = len(assignment_ids)
    if total_assignments == 0:
        return empty

    # 2b. Tất cả SessionResult thuộc các assignment đó (join qua session).
    results = (
        db_session.query(SessionResult)
        .join(ExerciseSession, SessionResult.session_id == ExerciseSession.id)
        .filter(ExerciseSession.assignment_id.in_(assignment_ids))
        .all()
    )

    # 3. Chưa có result nào -> cả 3 None.
    if not results:
        return empty

    # 4+6. accuracy_score & fluency_score — TÁI DÙNG attempt_to_metrics cho từng lượt
    # (single-source: "accuracy = score", "fluency = components['fluency']" chỉ định nghĩa
    # 1 nơi). Tổng hợp = trung bình các giá trị THÔ, bỏ qua None; làm tròn 1 lần ở cuối
    # (giữ y hệt hành vi cũ: round SAU khi trung bình, không round từng lượt).
    per_attempt = [
        attempt_to_metrics(r.score, r.components, r.result.value) for r in results
    ]
    accuracies = [m["accuracy_score"] for m in per_attempt if m["accuracy_score"] is not None]
    accuracy_score = sum(accuracies) / len(accuracies) if accuracies else None

    fluencies = [m["fluency_score"] for m in per_attempt if m["fluency_score"] is not None]
    fluency_score = sum(fluencies) / len(fluencies) if fluencies else None

    # 5. completion_score — CẤP PLAN ("tiến độ chương trình" / thẻ "Hoàn thành tuần"):
    # tỉ lệ (số assignment có >=1 session graded) / tổng assignment. KHÔNG lấy từ
    # attempt_to_metrics (ở đó completion là "độ phủ nội dung" cấp-1-lượt, khái niệm
    # KHÁC). ĐỊNH NGHĨA giữ nguyên như Bước 12, không đổi.
    graded_assignment_count = (
        db_session.query(ExerciseSession.assignment_id)
        .filter(
            ExerciseSession.assignment_id.in_(assignment_ids),
            ExerciseSession.status == SessionStatus.graded,
        )
        .distinct()
        .count()
    )
    completion_score = graded_assignment_count / total_assignments * 100

    # 7. Làm tròn 1 chữ số thập phân.
    return {
        "accuracy_score": _round1(accuracy_score),
        "completion_score": _round1(completion_score),
        "fluency_score": _round1(fluency_score),
    }


# ==============================================================================
# PROGRESS DASHBOARD — dữ liệu cho trang chủ bệnh nhân (biểu đồ/streak/từ hay sai)
# ==============================================================================

# ResultLabel coi là "KHÔNG ĐẠT" khi đếm từ hay sai (điểm dưới ngưỡng đạt / chọn sai).
_FAIL_RESULTS = (ResultLabel.retry, ResultLabel.incorrect, ResultLabel.near)


def _local_date(dt) -> date:
    """created_at (timestamptz) -> ngày theo múi giờ máy chủ (đủ cho MVP 1 múi giờ VN)."""
    return dt.astimezone().date()


def _target_word_of_exercise(exercise: Exercise) -> Optional[str]:
    """
    Từ MỤC TIÊU của 1 bài (cùng cách build_scoring_exercise xác định đáp án):
      - naming / command_identification : target_vocab.canonical_word
      - sentence_building               : target_sentence_instance.vocab.canonical_word
    Trả None nếu dữ liệu thiếu liên kết (không crash dashboard vì 1 bài hỏng).
    """
    if exercise.exercise_type in (ExerciseType.naming, ExerciseType.command_identification):
        vocab = exercise.target_vocab
        return vocab.canonical_word if vocab else None
    if exercise.exercise_type == ExerciseType.sentence_building:
        si = exercise.target_sentence_instance
        return si.vocab.canonical_word if si and si.vocab else None
    return None


def compute_daily_scores(
    db_session: Session, patient_id: uuid.UUID, days: int = 7
) -> list[dict]:
    """
    Tính điểm trung bình + session_count per-ngày cho N ngày gần nhất.

    SINGLE SOURCE cho công thức: avg(score)/day, count(SessionResult)/day.
    Dùng chung cho cả daily_scores (7 ngày) lẫn daily_scores_30 (30 ngày).

    Return: list[DailyScore dict], sắp cũ -> mới, kể cả ngày không tập (session_count=0, avg_score=None).
    """
    # Query mọi (result, session, exercise) của patient
    rows = (
        db_session.query(SessionResult, ExerciseSession, Exercise)
        .join(ExerciseSession, SessionResult.session_id == ExerciseSession.id)
        .join(ExerciseAssignment, ExerciseSession.assignment_id == ExerciseAssignment.id)
        .join(Exercise, ExerciseAssignment.exercise_id == Exercise.id)
        .filter(ExerciseSession.patient_id == patient_id)
        .all()
    )

    # Gom theo ngày
    by_day: dict[date, list[float]] = {}
    count_by_day: dict[date, int] = {}
    for result, _sess, _ex in rows:
        d = _local_date(result.created_at)
        count_by_day[d] = count_by_day.get(d, 0) + 1
        if result.score is not None:
            by_day.setdefault(d, []).append(result.score)

    # Xếp N ngày (cũ -> mới)
    today = date.today()
    daily_scores = []
    for offset in range(days - 1, -1, -1):
        d = today - timedelta(days=offset)
        scores = by_day.get(d)
        daily_scores.append({
            "date": d.isoformat(),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
            "session_count": count_by_day.get(d, 0),
        })

    return daily_scores


def compute_progress_dashboard(db_session: Session, patient_id: uuid.UUID) -> dict:
    """
    Dữ liệu cho GET /patients/me/progress-dashboard. Tính trên TOÀN BỘ lịch sử làm bài
    của patient (mọi plan) — dashboard là tiến trình cá nhân, không giới hạn 1 plan.

    Trả dict khớp ProgressDashboardResponse:
      - daily_scores: đúng 7 phần tử (7 ngày gần nhất, cũ -> mới, kể cả ngày không tập
        -> avg_score=None, session_count=0).
      - streak: current_streak_days đếm ngày LIÊN TIẾP có >=1 bài HOÀN THÀNH (session
        graded, theo completed_at); nếu HÔM NAY chưa tập thì cho phép chuỗi kết thúc ở
        HÔM QUA (chuỗi chưa đứt cho tới hết ngày). active_days_last_30: ngày có >=1
        LƯỢT LÀM BÀI bất kỳ (SessionResult) — thước đo "có luyện tập", rộng hơn "hoàn thành".
      - difficult_words: HEURISTIC ĐƠN GIẢN CHO MVP (có thể tinh chỉnh sau):
        với mỗi lượt làm (SessionResult, bỏ qua "invalid" — input rác không tính là gặp
        bài), từ mục tiêu = canonical_word của vocab liên quan; fail khi result thuộc
        retry/incorrect/near. Gom theo (word, exercise_type), chỉ giữ từ có >=1 lần fail,
        sắp giảm dần fail_count rồi attempts, tối đa 10.
    """
    today = date.today()

    # ── 1 query lấy mọi (result, exercise) của patient — dùng cho cả 3 nhóm ──
    rows = (
        db_session.query(SessionResult, ExerciseSession, Exercise)
        .join(ExerciseSession, SessionResult.session_id == ExerciseSession.id)
        .join(ExerciseAssignment, ExerciseSession.assignment_id == ExerciseAssignment.id)
        .join(Exercise, ExerciseAssignment.exercise_id == Exercise.id)
        .filter(ExerciseSession.patient_id == patient_id)
        .all()
    )

    # ── a) daily_scores: 7 ngày gần nhất + daily_scores_30: 30 ngày (dùng helper chung) ──
    # SINGLE SOURCE: compute_daily_scores() tính công thức GROUP BY ngày & avg/count cho cả 2.
    daily_scores = compute_daily_scores(db_session, patient_id, days=7)
    daily_scores_30 = compute_daily_scores(db_session, patient_id, days=30)

    # ── Tính lại count_by_day để phục vụ active_days_last_30 ──
    count_by_day: dict[date, int] = {}
    for result, _sess, _ex in rows:
        d = _local_date(result.created_at)
        count_by_day[d] = count_by_day.get(d, 0) + 1

    # ── b) streak ──
    # Ngày "hoàn thành bài": có >=1 session graded (theo completed_at).
    completed_days = {
        _local_date(sess.completed_at)
        for _r, sess, _ex in rows
        if sess.status == SessionStatus.graded and sess.completed_at is not None
    }
    streak = 0
    cursor = today if today in completed_days else today - timedelta(days=1)
    while cursor in completed_days:
        streak += 1
        cursor -= timedelta(days=1)

    active_days = sorted(
        d.isoformat()
        for d in count_by_day
        if today - timedelta(days=29) <= d <= today
    )

    # ── c) difficult_words (heuristic MVP) ──
    agg: dict[tuple[str, str], dict] = {}
    for result, _sess, exercise in rows:
        if result.result == ResultLabel.invalid:
            continue  # input rác (quá ngắn/không nghe được) — không tính là "gặp bài"
        word = _target_word_of_exercise(exercise)
        if not word:
            continue
        key = (word, exercise.exercise_type.value)
        entry = agg.setdefault(key, {"attempts": 0, "fail_count": 0})
        entry["attempts"] += 1
        if result.result in _FAIL_RESULTS:
            entry["fail_count"] += 1

    difficult_words = [
        {
            "word": word,
            "attempts": entry["attempts"],
            "fail_count": entry["fail_count"],
            "exercise_type": exercise_type,
        }
        for (word, exercise_type), entry in agg.items()
        if entry["fail_count"] >= 1
    ]
    difficult_words.sort(key=lambda w: (-w["fail_count"], -w["attempts"], w["word"]))

    return {
        "daily_scores": daily_scores,
        "daily_scores_30": daily_scores_30,
        "streak": {
            "current_streak_days": streak,
            "active_days_last_30": active_days,
        },
        "difficult_words": difficult_words[:10],
    }
