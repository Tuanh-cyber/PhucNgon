"""
Router: attempts — endpoint làm bài / preview chấm điểm.

Endpoint /attempt-preview CHƯA lưu kết quả vào database — chỉ dùng để test/preview.
Endpoint lưu thật (dùng save_session_result()) sẽ thêm sau khi có hệ thống
Patient/TherapyPlan/Assignment/Session.
"""

from __future__ import annotations

import logging
import random
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.content import CommandAsset, Exercise, VocabularyAsset
from app.models.enums import CommandMode, UserRole
from app.models.therapy import ExerciseAssignment, TherapyPlan
from app.models.user import User
from app.routers.auth import get_current_user
from app.schemas.attempt import (
    AttemptResponse,
    AttemptSubmitResponse,
    ExerciseInfoResponse,
    FeedbackItem,
)
from app.schemas.content import (
    AssignmentContent,
    CommandRecognitionContent,
    CommandRepetitionContent,
    NamingContent,
    RecognitionChoice,
    SentenceBuildingContent,
)
from app.services.asset_url_service import (
    command_audio_url,
    sentence_audio_url,
    vocab_audio_url,
    vocab_image_url,
)
from app.services.audio_service import AudioContentError, WavFormatError
from app.services.session_service import (
    FINAL_RESULT_LABELS,
    pick_distractors,
    process_attempt_preview,
    submit_attempt,
)
from app.services.stats_service import attempt_to_metrics, round_metric

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exercises", tags=["attempts"])

# Router riêng cho /assignments (nộp bài thật) — prefix khác /exercises.
assignments_router = APIRouter(prefix="/assignments", tags=["attempts"])


def _get_exercise_or_404(exercise_id: uuid.UUID, db: Session) -> Exercise:
    """Query Exercise theo id, raise HTTP 404 nếu không tồn tại."""
    db_exercise = db.query(Exercise).filter(Exercise.id == exercise_id).first()
    if db_exercise is None:
        raise HTTPException(
            status_code=404,
            detail=f"Không tìm thấy bài tập với id={exercise_id}",
        )
    return db_exercise


@router.get("/{exercise_id}", response_model=ExerciseInfoResponse)
def get_exercise_info(exercise_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Trả thông tin CƠ BẢN của 1 bài tập (không lộ đáp án đúng).
    """
    db_exercise = _get_exercise_or_404(exercise_id, db)
    return ExerciseInfoResponse(
        exercise_id=str(db_exercise.id),
        exercise_type=db_exercise.exercise_type.value,
        topic=db_exercise.topic.value,
        vocab_level=db_exercise.vocab_level,
        mode=db_exercise.mode.value if db_exercise.mode else None,
    )


@router.post("/{exercise_id}/attempt-preview", response_model=AttemptResponse)
async def attempt_preview(
    exercise_id: uuid.UUID,
    audio_file: Optional[UploadFile] = File(default=None),
    selected_vocab_id: Optional[str] = Form(default=None),
    attempt_number: int = Form(default=1),
    db: Session = Depends(get_db),
):
    """
    Chấm thử 1 lượt làm bài và trả ScoreResult — CHƯA lưu database.

    - Bài speech (naming / command repetition / sentence_building): cần audio_file.
    - Bài command_identification/recognition: cần selected_vocab_id, không cần audio.
    """
    db_exercise = _get_exercise_or_404(exercise_id, db)

    wav_bytes = await audio_file.read() if audio_file is not None else None

    try:
        score_result = process_attempt_preview(
            db_exercise=db_exercise,
            db_session=db,
            wav_bytes=wav_bytes,
            selected_vocab_id=selected_vocab_id,
            attempt_number=attempt_number,
        )
    except (WavFormatError, AudioContentError) as e:
        # Audio sai định dạng / nội dung không hợp lệ
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        # Thiếu distractor, sai loại bài, thiếu dữ liệu... từ session_service
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        # ASR service (ASR_MODE=real) không khả dụng — cùng cách xử lý với endpoint submit.
        logger.error("ASR service lỗi khi preview exercise=%s: %s", exercise_id, e)
        raise HTTPException(
            status_code=503,
            detail="Dịch vụ nhận diện giọng nói tạm thời không khả dụng. "
            "Vui lòng thử lại sau.",
        )

    return AttemptResponse.model_validate(score_result)


def _build_assignment_content(exercise: Exercise, db: Session) -> AssignmentContent:
    """
    Dựng payload nội dung 1 bài để frontend render — KHÔNG chứa đáp án đúng.

    Tái sử dụng đúng các quyết định của session_service.build_scoring_exercise():
      - CMD: CommandAsset tra theo GIÁ TRỊ target_vocab_id (không dùng target_command_id).
      - CMD recognition: bộ nhiễu lấy từ distractor_vocab_ids có sẵn, hoặc pick_distractors()
        với seed = str(command_asset.id) — Ý ĐỒ QUAN TRỌNG: cùng seed với lúc CHẤM, đảm bảo
        4 lựa chọn hiển thị khớp chính xác bộ đáp án mà scoring sẽ đối chiếu.
    """
    exercise_type = exercise.exercise_type.value

    if exercise_type == "naming":
        vocab = exercise.target_vocab
        return NamingContent(
            image_url=vocab_image_url(vocab),
            vocab_audio_url=vocab_audio_url(vocab),
        )

    if exercise_type == "command_identification":
        # CommandAsset khớp target_vocab_id — cùng cách tra của build_scoring_exercise.
        command_asset = (
            db.query(CommandAsset)
            .filter(CommandAsset.target_vocab_id == exercise.target_vocab_id)
            .first()
        )

        if exercise.mode == CommandMode.repetition:
            return CommandRepetitionContent(
                command_audio_url=command_audio_url(command_asset),
                image_url=vocab_image_url(exercise.target_vocab),
            )

        if exercise.mode == CommandMode.recognition:
            if command_asset is None:
                # Thiếu dữ liệu (giống ValueError bên scoring) -> 422 cho frontend biết rõ.
                raise HTTPException(
                    status_code=422,
                    detail=f"Bài '{exercise.exercise_code}': không tìm thấy CommandAsset "
                    f"cho target_vocab_id={exercise.target_vocab_id}",
                )
            if command_asset.distractor_vocab_ids:
                distractor_ids = [str(x) for x in command_asset.distractor_vocab_ids]
            else:
                distractor_ids = pick_distractors(
                    target_vocab=exercise.target_vocab,
                    db_session=db,
                    seed_key=str(command_asset.id),
                )

            # Load vocab của cả 4 lựa chọn (1 query), giữ target + 3 nhiễu.
            choice_ids = [uuid.UUID(x) for x in distractor_ids] + [exercise.target_vocab_id]
            vocab_rows = (
                db.query(VocabularyAsset).filter(VocabularyAsset.id.in_(choice_ids)).all()
            )
            choices = [
                RecognitionChoice(
                    vocab_id=str(v.id),
                    image_url=vocab_image_url(v),
                    word=v.canonical_word,
                )
                for v in vocab_rows
            ]
            # Trộn thứ tự — seed ổn định theo command_id (chuỗi seed KHÁC seed pick_distractors
            # để thứ tự không suy ra được từ bộ nhiễu), cùng 1 bài luôn hiện cùng 1 thứ tự.
            random.Random(f"shuffle:{command_asset.id}").shuffle(choices)
            return CommandRecognitionContent(
                command_audio_url=command_audio_url(command_asset),
                command_text=command_asset.command_text,
                choices=choices,
            )

        raise HTTPException(
            status_code=422,
            detail=f"Bài '{exercise.exercise_code}': mode CMD không hợp lệ = {exercise.mode}",
        )

    if exercise_type == "sentence_building":
        si = exercise.target_sentence_instance
        return SentenceBuildingContent(
            template_display=si.template.template,
            image_url=vocab_image_url(si.vocab),
            sentence_audio_url=sentence_audio_url(si),
        )

    raise HTTPException(
        status_code=422, detail=f"Loại bài không hỗ trợ: {exercise_type}"
    )


@assignments_router.get("/{assignment_id}/content", response_model=AssignmentContent)
def get_assignment_content(
    assignment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Nội dung chi tiết 1 bài để render UI (ảnh/audio/lựa chọn) — KHÔNG lộ đáp án.

    Yêu cầu đăng nhập; assignment phải thuộc patient đang đăng nhập (403 nếu không —
    cùng thông điệp với nhánh nộp bài để không tiết lộ assignment nào tồn tại).
    """
    if current_user.role != UserRole.patient:
        raise HTTPException(
            status_code=403, detail="Chỉ bệnh nhân mới xem được bài tập của mình"
        )

    assignment = (
        db.query(ExerciseAssignment)
        .join(TherapyPlan, ExerciseAssignment.plan_id == TherapyPlan.id)
        .filter(
            ExerciseAssignment.id == assignment_id,
            TherapyPlan.patient_id == current_user.id,
        )
        .first()
    )
    if assignment is None:
        raise HTTPException(
            status_code=403,
            detail="Assignment không tồn tại hoặc không thuộc bệnh nhân này",
        )

    return _build_assignment_content(assignment.exercise, db)


@assignments_router.post("/{assignment_id}/submit", response_model=AttemptSubmitResponse)
async def submit_assignment_attempt(
    assignment_id: uuid.UUID,
    audio_file: Optional[UploadFile] = File(default=None),
    selected_vocab_id: Optional[str] = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    NỘP BÀI thật cho 1 assignment: chấm điểm + LƯU session_results.

    - Yêu cầu đăng nhập, role phải là patient (403 nếu không).
    - Bài speech: gửi audio_file. CMD recognition: gửi selected_vocab_id.
    """
    if current_user.role != UserRole.patient:
        raise HTTPException(
            status_code=403, detail="Chỉ bệnh nhân mới được nộp bài của mình"
        )

    wav_bytes = await audio_file.read() if audio_file is not None else None

    try:
        saved, feedback, progression = submit_attempt(
            db_session=db,
            patient=current_user,
            assignment_id=assignment_id,
            wav_bytes=wav_bytes,
            selected_vocab_id=selected_vocab_id,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (WavFormatError, AudioContentError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        # ASR service (ASR_MODE=real) chết/timeout/trả lỗi — _transcribe_real ném RuntimeError.
        # Trả 503 message thân thiện, KHÔNG lộ traceback/URL nội bộ cho client;
        # chi tiết kỹ thuật ghi vào log server để debug.
        logger.error("ASR service lỗi khi nộp bài assignment=%s: %s", assignment_id, e)
        raise HTTPException(
            status_code=503,
            detail="Dịch vụ nhận diện giọng nói tạm thời không khả dụng. "
            "Vui lòng thử lại sau.",
        )

    # 3 tiêu chí RIÊNG lượt này — CÙNG hàm attempt_to_metrics với /patients/me/stats.
    metrics = attempt_to_metrics(saved.score, saved.components, saved.result.value)

    return AttemptSubmitResponse(
        score=saved.score,
        accuracy_score=round_metric(metrics["accuracy_score"]),
        completion_score=round_metric(metrics["completion_score"]),
        fluency_score=round_metric(metrics["fluency_score"]),
        result=saved.result.value,
        feedback=[FeedbackItem(**f) for f in feedback],
        feedback_messages=[f["text"] for f in feedback],  # rút gọn, tương thích client cũ
        transcript=saved.transcript,
        attempt_number=saved.attempt_number,
        is_final=saved.result.value in FINAL_RESULT_LABELS,
        leveled_up=progression["leveled_up"],
        new_level=progression["new_level"],
    )
