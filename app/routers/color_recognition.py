"""
Router: color-recognition — dạng bài NGHE AUDIO HỎI MÀU -> CHẠM Ô MÀU (GĐ2).

TÁI DÙNG Y NGUYÊN khuôn logic_sequence GĐ2 (đường nộp riêng, KHÔNG ASR/scoring engine):
  - ExerciseSession: assignment_id=NULL, color_recognition_exercise_id=<bài>;
    get-or-create in_progress để retry tăng attempt_number.
  - SessionResult: score=100|0 nhị phân, result=correct|retry,
    components={"binary_color": ...} — phiên đếm x/10 qua compute_session_counters.
  - CHỐT: sai = "retry" (cho làm lại — giống logic_sequence, khác CMD recognition).

Options 4 ô màu: 1 đúng + 3 nhiễu random.sample từ 11 màu còn lại, XÁO ở server mỗi
lần gọi (unseeded). Màu đúng KHÔNG đánh dấu — correct_color_id chỉ trả sau khi nộp.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.color_recognition import Color, ColorRecognitionExercise
from app.models.enums import ResultLabel, SessionStatus, UserRole
from app.models.therapy import ExerciseSession, SessionResult
from app.models.therapy_session import TherapySession
from app.models.user import User
from app.routers.auth import get_current_user
from app.routers.sessions import compute_session_counters
from app.schemas.color_recognition import (
    ColorOption,
    ColorRecognitionContent,
    ColorRecognitionSubmitRequest,
    ColorRecognitionSubmitResponse,
)
from app.services.asset_url_service import color_instruction_audio_url

router = APIRouter(prefix="/color-recognition", tags=["color-recognition"])

OPTION_COUNT = 4  # 1 đúng + 3 nhiễu


def _get_exercise_or_404(db: Session, exercise_code: str) -> ColorRecognitionExercise:
    ex = (
        db.query(ColorRecognitionExercise)
        .filter(ColorRecognitionExercise.exercise_code == exercise_code)
        .first()
    )
    if ex is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài nhận biết màu này")
    return ex


# ── LẤY BÀI ───────────────────────────────────────────────────────────────────
@router.get("/{exercise_code}", response_model=ColorRecognitionContent)
def get_color_recognition_content(
    exercise_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """4 ô màu (1 đúng + 3 nhiễu ngẫu nhiên, xáo server — mỗi lần gọi khác nhau)."""
    if current_user.role != UserRole.patient:
        raise HTTPException(status_code=403, detail="Chỉ bệnh nhân mới làm bài")

    ex = _get_exercise_or_404(db, exercise_code)
    target = ex.target_color

    others = (
        db.query(Color).filter(Color.id != target.id).all()
    )
    if len(others) < OPTION_COUNT - 1:
        raise HTTPException(status_code=422, detail="Không đủ màu nhiễu (cần seed đủ 12 màu)")
    distractors = random.sample(others, OPTION_COUNT - 1)  # unseeded — mỗi lần khác

    options = [target, *distractors]
    random.shuffle(options)  # xáo vị trí — client không suy được ô đúng

    return ColorRecognitionContent(
        exercise_code=ex.exercise_code,
        level=ex.level,
        instruction_audio_url=color_instruction_audio_url(ex.instruction_audio),
        question_color_name=target.name,
        options=[
            ColorOption(color_id=c.color_id, name=c.name, hex_code=c.hex_code)
            for c in options
        ],
    )


# ── NỘP / CHẤM ────────────────────────────────────────────────────────────────
@router.post("/{exercise_code}/submit", response_model=ColorRecognitionSubmitResponse)
def submit_color_recognition(
    exercise_code: str,
    payload: ColorRecognitionSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Chấm NHỊ PHÂN: chạm đúng màu -> 100/correct/completed; sai -> 0/retry (làm lại,
    attempt_number tăng — CHỐT giống logic_sequence). correct_color_id lộ SAU khi nộp.
    """
    if current_user.role != UserRole.patient:
        raise HTTPException(status_code=403, detail="Chỉ bệnh nhân mới được nộp bài")

    ex = _get_exercise_or_404(db, exercise_code)
    target = ex.target_color

    # selected phải là 1 màu có thật (không cần thuộc bộ 4 đã hiện — server không lưu bộ hiện)
    selected = (
        db.query(Color).filter(Color.color_id == payload.selected_color_id).first()
    )
    if selected is None:
        raise HTTPException(status_code=422, detail="selected_color_id không hợp lệ")

    # Validate phiên TRƯỚC khi ghi (cùng quy tắc submit bài nói + logic_sequence)
    therapy_session = None
    if payload.therapy_session_id is not None:
        try:
            ts_uuid = uuid.UUID(payload.therapy_session_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="therapy_session_id không hợp lệ")
        therapy_session = (
            db.query(TherapySession)
            .filter(
                TherapySession.id == ts_uuid,
                TherapySession.patient_id == current_user.id,
                TherapySession.status == "in_progress",
            )
            .first()
        )
        if therapy_session is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy phiên tập đang mở")

    is_correct = selected.id == target.id
    score = 100.0 if is_correct else 0.0

    # ── Ghi kết quả: CÙNG khuôn logic_sequence GĐ2 ──
    ex_session = (
        db.query(ExerciseSession)
        .filter(
            ExerciseSession.patient_id == current_user.id,
            ExerciseSession.color_recognition_exercise_id == ex.id,
            ExerciseSession.status == SessionStatus.in_progress,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if ex_session is None:
        ex_session = ExerciseSession(
            assignment_id=None,
            color_recognition_exercise_id=ex.id,
            patient_id=current_user.id,
            started_at=now,
            status=SessionStatus.in_progress,
        )
        db.add(ex_session)
        db.flush()

    attempt_number = (
        db.query(SessionResult).filter(SessionResult.session_id == ex_session.id).count() + 1
    )
    db.add(
        SessionResult(
            session_id=ex_session.id,
            attempt_number=attempt_number,
            score=score,
            is_correct=is_correct,
            result=ResultLabel.correct if is_correct else ResultLabel.retry,
            components={"binary_color": is_correct, "selected": selected.color_id},
        )
    )
    if is_correct:
        ex_session.status = SessionStatus.graded
        ex_session.completed_at = now

    if therapy_session is not None:
        ex_session.therapy_session_id = therapy_session.id
        db.flush()
        completed, retry = compute_session_counters(db, therapy_session.id)
        therapy_session.completed_count = completed
        therapy_session.total_retry_count = retry

    db.commit()

    return ColorRecognitionSubmitResponse(
        score=score,
        result="correct" if is_correct else "retry",
        completed=is_correct,
        is_correct=is_correct,
        attempt_number=attempt_number,
        correct_color_id=target.color_id,  # CHỈ lộ sau khi nộp
    )
