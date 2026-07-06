"""
PhụcNgôn — SESSION SERVICE (adapter + orchestrator thử nghiệm)
================================================================================
Owner: Tuấn Anh (Backend)

File này là "cầu nối" giữa 2 thế giới:
  - DB layer  : app.models.content.Exercise (SQLAlchemy model, 1 dòng trong DB)
  - Scoring   : app.services.scoring_service.ScoringExercise (dataclass thuần,
                input cho score())

Nhiệm vụ hiện tại (Bước 3):
  1. build_scoring_exercise()   — chuyển 1 dòng Exercise (DB) -> ScoringExercise
  2. process_attempt_preview()  — ráp thử audio + asr + scoring, CHƯA lưu DB

CHƯA làm ở bước này: lưu ScoreResult vào DB, tạo session mới.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.content import CommandAsset, Exercise
from app.models.enums import CommandMode, ResultLabel, SessionStatus
from app.models.therapy import (
    ExerciseAssignment,
    ExerciseSession,
    SessionResult,
    TherapyPlan,
    TopicProgress,
)
from app.services import asr_service, audio_service
from app.services.plan_service import add_level_up_assignments
from app.services.scoring_service import (
    MAX_VOCAB_LEVEL,
    ScoreResult,
    ScoringExercise,
    score,
)


# ==============================================================================
# DISTRACTOR PICKER — sinh đáp án nhiễu cho bài CMD recognition (runtime)
# ==============================================================================

def pick_distractors(target_vocab, db_session, k=3, seed_key=None) -> list[str]:
    """
    Chọn k vocab_id ngẫu nhiên làm đáp án nhiễu cho bài CMD recognition.

    target_vocab : VocabularyAsset của đáp án ĐÚNG.
    seed_key     : giá trị seed random (dùng command_id dạng string) — đảm bảo cùng 1 bài
                   luôn ra đúng 1 bộ đáp án nhiễu cố định qua các lần gọi khác nhau.

    NGUYÊN TẮC QUAN TRỌNG: đáp án nhiễu KHÔNG BAO GIỜ được lấy từ vocab_level CAO HƠN
    đáp án đúng — bệnh nhân chưa chắc đã học tới level đó, xuất hiện trong lựa chọn là
    không công bằng cho bài đánh giá. Chỉ được lấy cùng level hoặc THẤP HƠN.

    Thứ tự ưu tiên (dừng ngay khi đủ k ứng viên ở tầng nào, không xuống tầng tiếp theo
    nếu không cần thiết):
      Tầng 1: cùng topic, đúng vocab_level == target_vocab.vocab_level
      Tầng 2: cùng topic, vocab_level <= target_vocab.vocab_level (gộp cả tầng 1 + các
              level thấp hơn)
      Tầng 3 (chỉ dùng nếu Tầng 2 vẫn không đủ k): cùng topic, bỏ hoàn toàn điều kiện
              vocab_level (kể cả level cao hơn, chấp nhận rủi ro để có đủ 3 lựa chọn)
      Nếu Tầng 3 vẫn không đủ k -> raise ValueError, không được âm thầm trả về ít hơn k.
    """
    import random
    from app.models.content import VocabularyAsset

    # Tầng 1
    candidates = db_session.query(VocabularyAsset).filter(
        VocabularyAsset.topic == target_vocab.topic,
        VocabularyAsset.vocab_level == target_vocab.vocab_level,
        VocabularyAsset.id != target_vocab.id,
    ).all()

    # Tầng 2 — nếu Tầng 1 chưa đủ, mở rộng xuống level thấp hơn (KHÔNG cao hơn)
    if len(candidates) < k:
        candidates = db_session.query(VocabularyAsset).filter(
            VocabularyAsset.topic == target_vocab.topic,
            VocabularyAsset.vocab_level <= target_vocab.vocab_level,
            VocabularyAsset.id != target_vocab.id,
        ).all()

    # Tầng 3 — chỉ khi Tầng 2 vẫn không đủ, mới bỏ hẳn ràng buộc level
    if len(candidates) < k:
        candidates = db_session.query(VocabularyAsset).filter(
            VocabularyAsset.topic == target_vocab.topic,
            VocabularyAsset.id != target_vocab.id,
        ).all()

    if len(candidates) < k:
        raise ValueError(
            f"Không đủ từ vựng cùng topic '{target_vocab.topic}' để sinh {k} đáp án nhiễu "
            f"cho vocab_id={target_vocab.id} (chỉ có {len(candidates)} ứng viên kể cả sau "
            f"khi bỏ ràng buộc level, cần {k})"
        )

    rng = random.Random(seed_key)
    chosen = rng.sample(candidates, k)
    return [str(v.id) for v in chosen]


# ==============================================================================
# ADAPTER — 1 dòng Exercise (DB) -> ScoringExercise (dataclass cho scoring)
# ==============================================================================

def derive_missing_words(template_text: str, full_sentence: str,
                         fallback_word: str) -> list[str]:
    """
    Cắt phần khuyết THẬT của câu SEN: template 'Tôi có ___ cái áo' + full_sentence
    'Tôi có mười ba cái áo' -> ['mười ba'].

    VÌ SAO không dùng vocab.canonical_word: canonical có thể mang tiền tố phân loại
    KHÔNG xuất hiện trong câu (vd 'số mười ba' cho ảnh số 13) — nếu bắt bệnh nhân nói
    đúng canonical thì câu đúng tự nhiên 'bây giờ là mười ba giờ' không bao giờ đạt
    keyword. Phần khuyết đúng nghĩa là "chuỗi từ thay vào chỗ ___".

    So khớp prefix/suffix KHÔNG phân biệt hoa thường; template/full_sentence lệch nhau
    (dữ liệu hỏng) -> trả [fallback_word] (canonical) như hành vi cũ, không crash.
    """
    parts = re.split(r"_{2,}", " ".join(template_text.split()), maxsplit=1)
    if len(parts) == 2:
        prefix, suffix = parts[0].strip(), parts[1].strip()
        full = " ".join(full_sentence.split())
        low = full.lower()
        if low.startswith(prefix.lower()) and low.endswith(suffix.lower()):
            end = len(full) - len(suffix) if suffix else len(full)
            blank = full[len(prefix):end].strip()
            if blank:
                return [blank]
    return [fallback_word]


def build_scoring_exercise(db_exercise: Exercise, db_session: Session) -> ScoringExercise:
    """
    INPUT :
      - db_exercise : app.models.content.Exercise (SQLAlchemy, đã load từ DB)
      - db_session  : SQLAlchemy Session (cần cho case CMD recognition — phải query
                      CommandAsset khớp target_vocab_id)
    OUTPUT: ScoringExercise (dataclass) — input hợp lệ cho scoring_service.score().
    RAISE : ValueError nếu dữ liệu thiếu (vd CMD recognition không tìm thấy CommandAsset).

    Map theo db_exercise.exercise_type:

      naming:
        canonical_word/accepted_answers/accepted_classifiers lấy từ target_vocab.

      command_identification:
        target_vocab trỏ TRỰC TIẾP tới VocabularyAsset (theo thiết kế đã chốt —
        KHÔNG dùng target_command_id).
        - mode repetition : map giống naming (nói lại tên), thêm mode="repetition"
        - mode recognition: bài touch (không ASR). Cần distractor_vocab_ids từ
                            CommandAsset khớp target_vocab_id. mode="recognition"

      sentence_building:
        full_sentence từ target_sentence_instance; missing_words = phần khuyết THẬT
        của câu, cắt từ full_sentence theo khuôn template (xem derive_missing_words).

    GHI CHÚ THIẾT KẾ (sentence_building):
      TRƯỚC ĐÂY missing_words=[vocab.canonical_word] — SAI với vocab có tiền tố không
      xuất hiện trong câu: canonical 'số mười ba' nhưng câu là 'Bây giờ là mười ba giờ'
      -> bệnh nhân nói đúng vẫn bị "Còn thiếu từ 'số mười ba'". Nay cắt đúng phần
      thay vào chỗ ___ ('mười ba'); canonical_word chỉ còn là fallback khi dữ liệu
      template/full_sentence lệch nhau.
    """
    exercise_type = db_exercise.exercise_type.value

    # Các field chung cho mọi loại bài
    common = dict(
        exercise_id=str(db_exercise.id),
        exercise_type=exercise_type,
        vocab_level=db_exercise.vocab_level,
        topic=db_exercise.topic.value,
        duration_expected=db_exercise.duration_expected or 0.0,
    )

    # --- NAMING ---
    if exercise_type == "naming":
        vocab = db_exercise.target_vocab
        return ScoringExercise(
            **common,
            mode=None,
            canonical_word=vocab.canonical_word,
            accepted_answers=vocab.accepted_answers,
            accepted_classifiers=vocab.accepted_classifiers or [],
        )

    # --- COMMAND IDENTIFICATION ---
    if exercise_type == "command_identification":
        # target_vocab trỏ trực tiếp tới VocabularyAsset (không qua target_command_id)
        if db_exercise.mode == CommandMode.repetition:
            vocab = db_exercise.target_vocab
            return ScoringExercise(
                **common,
                mode="repetition",
                canonical_word=vocab.canonical_word,
                accepted_answers=vocab.accepted_answers,
                accepted_classifiers=vocab.accepted_classifiers or [],
            )

        if db_exercise.mode == CommandMode.recognition:
            # Tìm CommandAsset khớp GIÁ TRỊ target_vocab_id (không phải FK trực tiếp)
            command_asset = (
                db_session.query(CommandAsset)
                .filter(CommandAsset.target_vocab_id == db_exercise.target_vocab_id)
                .first()
            )
            if command_asset is None:
                raise ValueError(
                    f"CMD recognition exercise '{db_exercise.exercise_code}' "
                    f"(id={db_exercise.id}): không tìm thấy CommandAsset nào có "
                    f"target_vocab_id={db_exercise.target_vocab_id}"
                )
            # distractor_vocab_ids: nếu DB đã có sẵn (therapist ghi đè tay), dùng nguyên;
            # nếu None/rỗng, tính runtime bằng pick_distractors (seed theo command_id để
            # cùng 1 bài luôn ra đúng 1 bộ nhiễu cố định).
            if command_asset.distractor_vocab_ids:
                distractor_ids = [str(x) for x in command_asset.distractor_vocab_ids]
            else:
                distractor_ids = pick_distractors(
                    target_vocab=db_exercise.target_vocab,
                    db_session=db_session,
                    seed_key=str(command_asset.id),
                )
            return ScoringExercise(
                **common,
                mode="recognition",
                target_vocab_id=str(db_exercise.target_vocab_id),
                distractor_vocab_ids=distractor_ids,
            )

        raise ValueError(
            f"CMD exercise '{db_exercise.exercise_code}' (id={db_exercise.id}): "
            f"mode không hợp lệ = {db_exercise.mode}"
        )

    # --- SENTENCE BUILDING ---
    if exercise_type == "sentence_building":
        si = db_exercise.target_sentence_instance
        return ScoringExercise(
            **common,
            mode=None,
            full_sentence=si.full_sentence,
            missing_words=derive_missing_words(
                template_text=si.template.template,
                full_sentence=si.full_sentence,
                fallback_word=si.vocab.canonical_word,
            ),
        )

    raise ValueError(
        f"Loại bài không hỗ trợ: exercise_type={exercise_type} "
        f"(id={db_exercise.id})"
    )


# ==============================================================================
# ORCHESTRATOR (thử nghiệm) — ráp audio + asr + scoring, CHƯA lưu DB
# ==============================================================================

def process_attempt_preview(
    db_exercise: Exercise,
    db_session: Session,
    wav_bytes: Optional[bytes] = None,
    selected_vocab_id: Optional[str] = None,
    attempt_number: int = 1,
) -> ScoreResult:
    """
    Ráp thử toàn bộ pipeline cho 1 lượt làm bài, trả về ScoreResult để kiểm tra
    bằng mắt. KHÔNG lưu vào database (đó là việc của bước sau).

    INPUT :
      - db_exercise       : Exercise (DB) của bài đang làm
      - db_session        : SQLAlchemy Session
      - wav_bytes         : bytes WAV bệnh nhân ghi (cho bài speech)
      - selected_vocab_id : id vocab bệnh nhân tap (chỉ CMD recognition)
      - attempt_number    : lần thử (chỉ để thống kê used_fallback — KHÔNG còn trừ điểm)
    OUTPUT: ScoreResult (chưa lưu DB).

    LUỒNG:
      - CMD recognition : score() trực tiếp bằng selected_vocab_id (không audio/ASR)
      - Còn lại (speech): audio_service.process_audio() -> asr_service.transcribe_audio()
                          -> score()
    """
    scoring_ex = build_scoring_exercise(db_exercise, db_session)

    # --- CMD recognition: touch, không cần audio/ASR ---
    if scoring_ex.exercise_type == "command_identification" and scoring_ex.mode == "recognition":
        return score(scoring_ex, selected_vocab_id=selected_vocab_id or "")

    # --- Bài speech: audio -> ASR -> scoring ---
    audio_info = audio_service.process_audio(wav_bytes)
    asr_result = asr_service.transcribe_audio(audio_info.trimmed_wav_bytes)

    return score(
        scoring_ex,
        transcript=asr_result["transcript"],
        audio_duration=audio_info.speech_duration_s,
        asr_confidence=asr_result["confidence"],
        attempt_number=attempt_number,
    )


# ==============================================================================
# PERSISTENCE — lưu 1 ScoreResult thành 1 dòng session_results (chưa commit)
# ==============================================================================

def save_session_result(db_session, session_id, score_result) -> SessionResult:
    """
    Lưu 1 ScoreResult (kết quả tính từ score(), object trong bộ nhớ) thành 1 dòng thật
    trong bảng session_results, gắn với session_id đã tồn tại.

    QUAN TRỌNG: hàm này KHÔNG tự commit() — chỉ add() + flush() để caller (vd router sau
    này, hoặc test) tự quyết định khi nào commit thật hoặc rollback.
    """
    # Map result (string) -> ResultLabel enum THEO VALUE (ResultLabel.pass_ có value="pass").
    # Không khớp -> raise ValueError rõ ràng, KHÔNG âm thầm gán mặc định.
    try:
        result_enum = ResultLabel(score_result.result)
    except ValueError:
        raise ValueError(
            f"score_result.result='{score_result.result}' không khớp giá trị hợp lệ nào "
            f"trong ResultLabel {[e.value for e in ResultLabel]}"
        )

    # selected_vocab_id (string/None/rỗng) -> UUID hoặc None (cột DB kiểu UUID nullable).
    raw_selected = score_result.selected_vocab_id
    selected_vocab_id = uuid.UUID(raw_selected) if raw_selected else None

    row = SessionResult(
        session_id=session_id,
        attempt_number=score_result.attempt_number,
        transcript=score_result.transcript,
        selected_vocab_id=selected_vocab_id,
        audio_duration_s=score_result.audio_duration_s,
        asr_confidence=score_result.asr_confidence,
        score=score_result.score,
        raw_score=score_result.raw_score,
        weighted_score=score_result.weighted_score,
        is_correct=score_result.is_correct,
        components=score_result.components,
        result=result_enum,
        used_fallback_audio=score_result.used_fallback_audio,
    )
    db_session.add(row)
    db_session.flush()
    return row


# ==============================================================================
# FEEDBACK — dịch components (số liệu thô) -> câu nhận xét tiếng Việt cho UI
# ==============================================================================

# ResultLabel coi là "KẾT THÚC" 1 lượt bài (đóng session -> graded).
# Đọc từ app/models/enums.ResultLabel: pass/correct/incorrect/skip là kết quả cuối cùng
# (đạt, hoặc chọn sai CMD, hoặc bỏ qua). near/retry/invalid -> CHƯA kết thúc, cho thử lại
# (giữ session in_progress) — đặc biệt SEN cho retry nhiều lần (mọi lần chấm công bằng).
FINAL_RESULT_LABELS = frozenset({"pass", "correct", "incorrect", "skip"})

# Ngưỡng "điểm cao" cho progression BỀN VỮNG theo topic (rule.md mục 2):
# 3 lần LIÊN TIẾP score >= 80 cùng topic -> +1 vocab level (tối đa MAX_VOCAB_LEVEL).
# LƯU Ý: khác streak trong scoring_service.update_vocab_level (đếm theo result pass/correct,
# chỉ sống trong 1 session) — TopicProgress đếm theo SCORE >= 80 và lưu DB xuyên session,
# đúng nguyên văn rule.md ("three consecutive exercise scores of at least 80%").
HIGH_SCORE_THRESHOLD = 80.0
CONSECUTIVE_HIGH_SCORES_TO_LEVEL_UP = 3


def _update_topic_progress(
    db_session: Session,
    patient,
    exercise: Exercise,
    plan: TherapyPlan,
    score_value: Optional[float],
) -> dict:
    """
    Cập nhật TopicProgress của (patient, topic) sau 1 lượt bài ĐÃ KẾT THÚC (graded).

    - score >= 80 -> consecutive_high_scores += 1; < 80 (hoặc None) -> reset 0.
    - Đủ 3 lần liên tiếp VÀ current_level < 3 -> +1 level, reset counter, giao thêm
      EXERCISES_PER_TYPE bài mới (cùng loại + topic, ở level mới) vào plan.

    KHÔNG commit — chạy trong cùng transaction với save_session_result.
    RETURN: {"leveled_up": bool, "new_level": int|None}
    """
    progress = (
        db_session.query(TopicProgress)
        .filter(
            TopicProgress.patient_id == patient.id,
            TopicProgress.topic == exercise.topic,
        )
        .first()
    )
    if progress is None:
        progress = TopicProgress(
            patient_id=patient.id,
            topic=exercise.topic,
            current_level=1,
            consecutive_high_scores=0,
        )
        db_session.add(progress)
        db_session.flush()

    if score_value is not None and score_value >= HIGH_SCORE_THRESHOLD:
        progress.consecutive_high_scores += 1
    else:
        progress.consecutive_high_scores = 0

    if (
        progress.consecutive_high_scores >= CONSECUTIVE_HIGH_SCORES_TO_LEVEL_UP
        and progress.current_level < MAX_VOCAB_LEVEL
    ):
        progress.current_level += 1
        progress.consecutive_high_scores = 0
        # Giao thêm bài KHÓ HƠN cùng loại + topic để lượt sau có thử thách mới.
        add_level_up_assignments(
            db_session,
            plan=plan,
            exercise_type=exercise.exercise_type,
            vocab_level=progress.current_level,
            topic=exercise.topic,
        )
        return {"leveled_up": True, "new_level": progress.current_level}

    return {"leveled_up": False, "new_level": None}


# Câu nhận xét thân thiện cho từng MÃ input rác (khớp is_invalid_input trong
# scoring_service — các câu này chính là ghi chú tiếng Việt cạnh mỗi mã lỗi ở đó).
INVALID_INPUT_MESSAGES = {
    "AUDIO_TOO_SHORT": "Hãy nói to và rõ hơn nhé!",
    "EMPTY_TRANSCRIPT": "Chưa nghe thấy gì, thử lại nhé!",
    "LOW_CONFIDENCE": "Hệ thống chưa nghe rõ, nói lại nhé!",
}

# Ngưỡng fluency coi là "nói chưa đều nhịp" -> gợi ý (CHỈ hiển thị, không trừ điểm).
_FLUENCY_HINT_THRESHOLD = 50


def build_feedback(
    exercise_type: str, components: dict, transcript: str, result: str
) -> list[dict]:
    """
    Suy 1–3 câu nhận xét tiếng Việt (CÓ phân loại type) từ components + result.

    ĐÂY LÀ QUYẾT ĐỊNH HIỂN THỊ, KHÔNG PHẢI LOGIC CHẤM ĐIỂM — chỉ đọc lại con số đã có
    sẵn trong components, không tính toán điểm gì mới. Trả [] nếu không xác định được
    (KHÔNG raise — đây chỉ là hiển thị phụ).

    Mỗi phần tử: {"type": "ok"|"warn", "text": str}
      - "ok"   : điều bệnh nhân làm ĐÚNG (tô xanh)
      - "warn" : điều cần cải thiện / lỗi input (tô vàng/đỏ)

    LƯU Ý (sentence_building): missing_words KHÔNG nằm trong components gốc. Caller
    (submit_attempt) truyền kèm key "missing_words" vào dict CHỈ để dựng feedback —
    dict lưu DB vẫn là components gốc, không bị đổi.
    """
    items: list[dict] = []
    if not isinstance(components, dict) or not components:
        return items

    # 0. Input rác (result "invalid"): dùng câu thân thiện theo mã lỗi trong components.
    if result == "invalid":
        code = components.get("error")
        items.append({
            "type": "warn",
            "text": INVALID_INPUT_MESSAGES.get(code, "Chưa nghe rõ, mình thử lại nhé!"),
        })
        return items

    # 1. naming + CMD repetition: có keyword/text_similarity/classifier/fluency.
    # CMD recognition chỉ có binary_touch -> không có "keyword" -> bỏ qua (bài touch không
    # nhận xét phát âm; đúng/sai đã thể hiện qua result correct/incorrect).
    if exercise_type in ("naming", "command_identification"):
        if "keyword" in components or "text_similarity" in components:
            keyword = components.get("keyword") or 0
            similarity = components.get("text_similarity") or 0
            if keyword >= 100:
                items.append({"type": "ok", "text": "Đã gọi đúng tên"})
            elif similarity >= 60:
                items.append({"type": "warn", "text": "Phát âm chưa rõ, gần đúng"})
            else:
                items.append({"type": "warn", "text": "Chưa nhận diện được từ đã nói"})
            # classifier_present == 0 chỉ xảy ra khi bài CÓ accepted_classifiers mà nói
            # sai/thiếu (bài không cần loại từ -> scoring trả 100, không vào nhánh này).
            if components.get("classifier_present") == 0:
                items.append({
                    "type": "warn",
                    "text": "Thiếu hoặc sai loại từ (vd 'cái', 'con'...)",
                })

    # 2. sentence_building: nhận xét theo từng từ khuyết.
    elif exercise_type == "sentence_building":
        missing_words = components.get("missing_words") or []
        norm_trans = (transcript or "").lower()
        trans_tokens = norm_trans.split()
        for word in missing_words:
            wl = str(word).lower()
            present = wl in trans_tokens or wl in norm_trans
            if present:
                items.append({"type": "ok", "text": f"Đã nói đúng từ '{word}'"})
            else:
                items.append({"type": "warn", "text": f"Còn thiếu từ '{word}'"})

    # 3. Gợi ý nhịp nói (mọi bài speech có key fluency): nói quá nhanh/chậm -> nhắc nhẹ.
    fluency = components.get("fluency")
    if isinstance(fluency, (int, float)) and fluency < _FLUENCY_HINT_THRESHOLD:
        items.append({
            "type": "warn",
            "text": "Nói chưa đều nhịp, thử nói thong thả hơn nhé",
        })

    return items


# ==============================================================================
# SUBMIT — nộp bài THẬT: chấm + LƯU session_results (khác preview: có commit)
# ==============================================================================

def submit_attempt(
    db_session: Session,
    patient,
    assignment_id,
    wav_bytes: Optional[bytes] = None,
    selected_vocab_id: Optional[str] = None,
) -> tuple[SessionResult, list[dict], dict]:
    """
    Luồng "nộp bài" thật — khác process_attempt_preview() ở chỗ CÓ LƯU vào database.

    RETURN: (SessionResult vừa lưu,
             feedback: list[{"type": "ok"|"warn", "text": str}] — câu nhận xét có phân loại,
             progression dict {"leveled_up": bool, "new_level": int|None}).
    RAISE :
      - PermissionError nếu assignment không thuộc patient này.
      - WavFormatError/AudioContentError/ValueError lan ra từ pipeline audio/scoring.
    """
    # 1. Lấy assignment + xác nhận thuộc đúng patient (join qua TherapyPlan.patient_id)
    assignment = (
        db_session.query(ExerciseAssignment)
        .join(TherapyPlan, ExerciseAssignment.plan_id == TherapyPlan.id)
        .filter(
            ExerciseAssignment.id == assignment_id,
            TherapyPlan.patient_id == patient.id,
        )
        .first()
    )
    if assignment is None:
        raise PermissionError(
            f"Assignment {assignment_id} không tồn tại hoặc không thuộc bệnh nhân "
            f"{patient.id} — không được nộp bài của người khác."
        )

    # 2. Tìm session in_progress của assignment; chưa có thì tạo mới
    session = (
        db_session.query(ExerciseSession)
        .filter(
            ExerciseSession.assignment_id == assignment.id,
            ExerciseSession.status == SessionStatus.in_progress,
        )
        .order_by(ExerciseSession.started_at.desc())
        .first()
    )
    if session is None:
        session = ExerciseSession(
            assignment_id=assignment.id,
            patient_id=patient.id,
            started_at=datetime.now(timezone.utc),
            status=SessionStatus.in_progress,
        )
        db_session.add(session)
        db_session.flush()

    # 3. attempt_number = số SessionResult đã có của session này + 1 (đúng logic retry SEN)
    prior_attempts = (
        db_session.query(SessionResult)
        .filter(SessionResult.session_id == session.id)
        .count()
    )
    attempt_number = prior_attempts + 1

    # 4. Chấm điểm (mirror process_attempt_preview, thêm attempt_number vừa tính)
    scoring_ex = build_scoring_exercise(assignment.exercise, db_session)
    if scoring_ex.exercise_type == "command_identification" and scoring_ex.mode == "recognition":
        score_result = score(
            scoring_ex,
            selected_vocab_id=selected_vocab_id or "",
            attempt_number=attempt_number,
        )
    else:
        audio_info = audio_service.process_audio(wav_bytes)
        asr_result = asr_service.transcribe_audio(audio_info.trimmed_wav_bytes)
        score_result = score(
            scoring_ex,
            transcript=asr_result["transcript"],
            audio_duration=audio_info.speech_duration_s,
            asr_confidence=asr_result["confidence"],
            attempt_number=attempt_number,
        )

    # 5. LƯU thật vào session_results (flush, chưa commit)
    saved = save_session_result(db_session, session_id=session.id, score_result=score_result)

    # 6. Cập nhật trạng thái session theo result
    is_final = score_result.result in FINAL_RESULT_LABELS
    if is_final:
        session.status = SessionStatus.graded
        session.completed_at = datetime.now(timezone.utc)
    # else (near/retry/invalid): giữ in_progress để lần sau tăng attempt_number tiếp

    # 6b. Progression theo topic (rule.md): CHỈ tính khi lượt bài KẾT THÚC (graded) —
    # attempt retry giữa chừng (SEN) chưa phải "hoàn thành 1 bài" nên không tính streak.
    # Cùng transaction với SessionResult: lên level + giao bài mới commit chung 1 lần.
    progression = {"leveled_up": False, "new_level": None}
    if is_final:
        progression = _update_topic_progress(
            db_session,
            patient=patient,
            exercise=assignment.exercise,
            plan=assignment.plan,
            score_value=score_result.score,
        )

    # 7. Câu nhận xét CÓ PHÂN LOẠI (truyền kèm missing_words CHỈ để dựng feedback, không
    # lưu DB). Trả list[{"type","text"}]; router tách text ra feedback_messages (list[str]).
    feedback_components = dict(score_result.components)
    feedback_components["missing_words"] = scoring_ex.missing_words
    feedback = build_feedback(
        score_result.exercise_type,
        feedback_components,
        score_result.transcript or "",
        score_result.result,
    )

    # 8. Commit thật — đã đi hết 1 lượt nộp bài trọn vẹn
    db_session.commit()
    db_session.refresh(saved)

    return saved, feedback, progression
