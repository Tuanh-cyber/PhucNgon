"""
Router: logic-sequence — dạng bài SẮP XẾP ẢNH (GĐ2: lấy bài + nộp/chấm).

ĐƯỜNG NỘP TÁCH RIÊNG khỏi submit_attempt bài nói (bài nói giả định audio/transcript/ASR
— dạng này KHÔNG có). Nhưng kết quả ghi VÀO CÙNG ExerciseSession/SessionResult:
  - ExerciseSession: assignment_id=NULL, logic_sequence_exercise_id=<bài>, status
    graded khi đúng / in_progress khi sai (cho retry — attempt_number tăng dần).
  - SessionResult: score=100|0 (NHỊ PHÂN, đường "non-weight" — không có 3 thành phần
    accuracy/completion/fluency), result=correct|retry, components={"binary_order":...}.
  -> phiên (therapy_sessions) đếm x/10 qua compute_session_counters y như bài nói.

Chấm: so ordered_step_ids với thứ tự đúng (sequence_steps.step_order). Thứ tự đúng
KHÔNG BAO GIỜ trả ở content — chỉ trả correct_order SAU khi nộp.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.enums import ResultLabel, SessionStatus, UserRole
from app.models.sequence import LogicSequenceExercise
from app.models.therapy import ExerciseSession, SessionResult
from app.models.therapy_session import TherapySession
from app.models.user import User
from app.routers.auth import get_current_user
from app.routers.sessions import compute_session_counters
from app.schemas.logic_sequence import (
    LogicSequenceContent,
    LogicSequenceSubmitRequest,
    LogicSequenceSubmitResponse,
    SequenceStepItem,
    StepFeedback,
)
from app.services.asset_url_service import instruction_audio_url, sequence_image_url

router = APIRouter(prefix="/logic-sequence", tags=["logic-sequence"])


def _get_exercise_or_404(db: Session, exercise_id: uuid.UUID) -> LogicSequenceExercise:
    ex = (
        db.query(LogicSequenceExercise)
        .filter(LogicSequenceExercise.id == exercise_id)
        .first()
    )
    if ex is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài sắp xếp này")
    return ex


# ── LẤY BÀI ───────────────────────────────────────────────────────────────────
@router.get("/{exercise_id}", response_model=LogicSequenceContent)
def get_logic_sequence_content(
    exercise_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Nội dung 1 bài sắp xếp: ảnh các bước ĐÃ XÁO Ở SERVER (mỗi lần gọi xáo lại —
    client chỉ thấy step_id + ảnh, KHÔNG biết thứ tự đúng) + audio hướng dẫn.
    """
    if current_user.role != UserRole.patient:
        raise HTTPException(status_code=403, detail="Chỉ bệnh nhân mới làm bài")

    ex = _get_exercise_or_404(db, exercise_id)
    seq = ex.target_sequence
    steps = list(seq.steps)  # đã order_by step_order từ relationship
    random.shuffle(steps)    # xáo THẬT mỗi lần gọi (không seed — spec yêu cầu)

    return LogicSequenceContent(
        exercise_id=str(ex.id),
        title=seq.title,
        level=seq.level,
        step_count=seq.step_count,
        instruction_audio_url=instruction_audio_url(),
        steps=[
            SequenceStepItem(step_id=str(s.id), image_url=sequence_image_url(s))
            for s in steps
        ],
    )


# ── NỘP / CHẤM ────────────────────────────────────────────────────────────────
@router.post("/{exercise_id}/submit", response_model=LogicSequenceSubmitResponse)
def submit_logic_sequence(
    exercise_id: uuid.UUID,
    payload: LogicSequenceSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Chấm NHỊ PHÂN: khớp HOÀN TOÀN thứ tự đúng -> score=100 (result=correct, hoàn thành);
    sai >=1 vị trí -> score=0 (result=retry — khuyến khích làm lại, rule ≤50).
    step_feedback đánh dấu từng vị trí đúng/sai tuyệt đối (cho FE tô màu).
    """
    if current_user.role != UserRole.patient:
        raise HTTPException(status_code=403, detail="Chỉ bệnh nhân mới được nộp bài")

    ex = _get_exercise_or_404(db, exercise_id)
    seq = ex.target_sequence

    # Thứ tự ĐÚNG theo step_order (nguồn chấm duy nhất)
    correct_ids = [str(s.id) for s in seq.steps]  # relationship đã sort step_order

    submitted = payload.ordered_step_ids
    if sorted(submitted) != sorted(correct_ids):
        raise HTTPException(
            status_code=422,
            detail="ordered_step_ids phải gồm ĐÚNG toàn bộ các bước của bài (không thiếu/thừa/lạ)",
        )

    # Validate phiên TRƯỚC khi ghi (cùng quy tắc với submit bài nói)
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

    # Chấm nhị phân + feedback từng vị trí (correct = đúng vị trí TUYỆT ĐỐI)
    is_match = submitted == correct_ids
    score = 100.0 if is_match else 0.0
    step_feedback = [
        StepFeedback(step_id=sid, position=i + 1, correct=sid == correct_ids[i])
        for i, sid in enumerate(submitted)
    ]

    # ── Ghi kết quả: CÙNG ExerciseSession/SessionResult với bài nói ──
    # Tái dùng 1 ExerciseSession in_progress cho (patient, bài) để retry tăng attempt_number
    # (đúng cách bài nói làm với near/retry).
    ex_session = (
        db.query(ExerciseSession)
        .filter(
            ExerciseSession.patient_id == current_user.id,
            ExerciseSession.logic_sequence_exercise_id == ex.id,
            ExerciseSession.status == SessionStatus.in_progress,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if ex_session is None:
        ex_session = ExerciseSession(
            assignment_id=None,                     # dạng này KHÔNG có assignment
            logic_sequence_exercise_id=ex.id,
            patient_id=current_user.id,
            started_at=now,
            status=SessionStatus.in_progress,
        )
        db.add(ex_session)
        db.flush()

    attempt_number = (
        db.query(SessionResult).filter(SessionResult.session_id == ex_session.id).count() + 1
    )
    result_label = ResultLabel.correct if is_match else ResultLabel.retry
    db.add(
        SessionResult(
            session_id=ex_session.id,
            attempt_number=attempt_number,
            score=score,
            is_correct=is_match,
            result=result_label,
            components={"binary_order": is_match, "step_count": seq.step_count},
        )
    )
    if is_match:
        ex_session.status = SessionStatus.graded
        ex_session.completed_at = now

    # Gắn vào phiên + cập nhật tiến độ (x/10) — cùng cơ chế bài nói
    if therapy_session is not None:
        ex_session.therapy_session_id = therapy_session.id
        db.flush()
        completed, retry = compute_session_counters(db, therapy_session.id)
        therapy_session.completed_count = completed
        therapy_session.total_retry_count = retry

    db.commit()

    return LogicSequenceSubmitResponse(
        score=score,
        result="correct" if is_match else "retry",
        completed=is_match,
        attempt_number=attempt_number,
        step_feedback=step_feedback,
        correct_order=correct_ids,  # CHỈ lộ SAU khi nộp
    )
