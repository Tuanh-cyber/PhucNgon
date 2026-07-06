"""
Test suite cho app.services.session_service — DÙNG DỮ LIỆU THẬT TỪ DATABASE.

Khác với các test service khác (dùng data giả), file này mở kết nối thật tới DB
đã seed (SessionLocal) để kiểm tra adapter build_scoring_exercise() hoạt động đúng
với 3 loại bài thật trong Exercise bank.

Yêu cầu: DB phải đã seed (90 naming, 124 command_identification, 89 sentence_building).
"""

import uuid
from datetime import date, datetime, timezone

import pytest

from app.core.database import SessionLocal
from app.models.content import Exercise, VocabularyAsset
from app.models.enums import CommandMode, ExerciseType, Gender, ResultLabel, Topic
from app.models.therapy import (
    ExerciseAssignment,
    ExerciseSession,
    SessionResult,
    TherapyPlan,
)
from app.models.user import Patient, Therapist
from app.services.scoring_service import score
from app.services.session_service import (
    build_scoring_exercise,
    derive_missing_words,
    pick_distractors,
    save_session_result,
)


@pytest.fixture
def db_session():
    """Mở 1 session DB thật, tự đóng sau mỗi test."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_build_naming_exercise(db_session):
    """NAMING: canonical_word khác rỗng, accepted_answers là list không rỗng."""
    db_exercise = (
        db_session.query(Exercise)
        .filter(Exercise.exercise_type == ExerciseType.naming)
        .first()
    )
    assert db_exercise is not None, "Không tìm thấy bài naming nào trong DB — đã seed chưa?"

    scoring_ex = build_scoring_exercise(db_exercise, db_session)

    assert scoring_ex.exercise_type == "naming"
    assert scoring_ex.mode is None
    assert scoring_ex.canonical_word != ""
    assert isinstance(scoring_ex.accepted_answers, list)
    assert len(scoring_ex.accepted_answers) > 0


def test_build_command_identification_recognition(db_session):
    """
    CMD recognition: target_vocab_id khác rỗng, distractor_vocab_ids có đúng 3 phần tử
    (sinh runtime bởi pick_distractors), không trùng target, và ỔN ĐỊNH qua các lần gọi
    (nhờ seed theo command_id).
    """
    db_exercise = (
        db_session.query(Exercise)
        .filter(
            Exercise.exercise_type == ExerciseType.command_identification,
            Exercise.mode == CommandMode.recognition,
        )
        .first()
    )
    assert db_exercise is not None, (
        "Không tìm thấy bài command_identification/recognition nào — đã seed chưa?"
    )

    scoring_ex = build_scoring_exercise(db_exercise, db_session)

    assert scoring_ex.exercise_type == "command_identification"
    assert scoring_ex.mode == "recognition"
    assert scoring_ex.target_vocab_id != ""

    # 3 đáp án nhiễu, không trùng đáp án đúng
    assert len(scoring_ex.distractor_vocab_ids) == 3
    assert scoring_ex.target_vocab_id not in scoring_ex.distractor_vocab_ids

    # Ổn định: gọi lần 2 cho cùng bài -> đúng bộ nhiễu như lần đầu (nhờ seed)
    scoring_ex_2 = build_scoring_exercise(db_exercise, db_session)
    assert scoring_ex_2.distractor_vocab_ids == scoring_ex.distractor_vocab_ids


def test_build_sentence_building_exercise(db_session):
    """SEN: full_sentence khác rỗng, missing_words là list có đúng 1 phần tử."""
    db_exercise = (
        db_session.query(Exercise)
        .filter(Exercise.exercise_type == ExerciseType.sentence_building)
        .first()
    )
    assert db_exercise is not None, (
        "Không tìm thấy bài sentence_building nào — đã seed chưa?"
    )

    scoring_ex = build_scoring_exercise(db_exercise, db_session)

    assert scoring_ex.exercise_type == "sentence_building"
    assert scoring_ex.mode is None
    assert scoring_ex.full_sentence != ""
    assert isinstance(scoring_ex.missing_words, list)
    assert len(scoring_ex.missing_words) == 1
    # Phần khuyết phải xuất hiện NGUYÊN VĂN trong câu (cắt từ full_sentence,
    # không còn lấy canonical_word có tiền tố lạ kiểu 'số mười ba')
    assert scoring_ex.missing_words[0].lower() in scoring_ex.full_sentence.lower()


def test_derive_missing_words():
    """Phần khuyết = chuỗi thay vào chỗ ___ của template, KHÔNG phải canonical_word."""
    # Ca lỗi user báo: canonical 'số mười ba' nhưng câu chỉ chứa 'mười ba'
    assert derive_missing_words(
        "Bây giờ là ___ giờ", "Bây giờ là mười ba giờ", "số mười ba"
    ) == ["mười ba"]
    assert derive_missing_words(
        "Tôi có ___ cái áo", "Tôi có mười một cái áo", "số mười một"
    ) == ["mười một"]
    # Khuyết ở cuối câu (suffix rỗng)
    assert derive_missing_words(
        "Tôi muốn ăn ____", "Tôi muốn ăn khoai lang", "khoai lang"
    ) == ["khoai lang"]
    # Khuyết ở đầu câu (prefix rỗng)
    assert derive_missing_words(
        "____ đang ở nhà", "Bố đang ở nhà", "bố"
    ) == ["Bố"]
    # Dữ liệu lệch (template không khớp câu) -> fallback canonical, không crash
    assert derive_missing_words(
        "Bây giờ là ___ giờ", "Tôi có ba cái áo", "số ba"
    ) == ["số ba"]


# ==============================================================================
# pick_distractors — nguyên tắc "không nhiễu ở level CAO HƠN đáp án đúng"
# ==============================================================================


def test_pick_distractors_never_picks_higher_level(db_session):
    """
    Với đáp án đúng ở vocab_level == 1, MỌI đáp án nhiễu sinh ra phải có
    vocab_level <= 1 (không được lấy từ level cao hơn).
    """
    target = (
        db_session.query(VocabularyAsset)
        .filter(VocabularyAsset.vocab_level == 1)
        .first()
    )
    assert target is not None, "Không tìm thấy vocab level 1 nào — đã seed chưa?"

    distractor_ids = pick_distractors(
        target_vocab=target, db_session=db_session, seed_key="test-seed"
    )

    for vid in distractor_ids:
        v = (
            db_session.query(VocabularyAsset)
            .filter(VocabularyAsset.id == uuid.UUID(vid))
            .first()
        )
        assert v is not None
        assert v.vocab_level <= 1, (
            f"Đáp án nhiễu {vid} có vocab_level={v.vocab_level} > 1 (đáp án đúng) — "
            f"vi phạm nguyên tắc không lấy nhiễu ở level cao hơn"
        )


# --- Fake DB để mô phỏng topic chỉ có 2 vocab (không đụng dữ liệu thật) ---


class _FakeVocab:
    def __init__(self, id, topic, vocab_level):
        self.id = id
        self.topic = topic
        self.vocab_level = vocab_level


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *args, **kwargs):
        return _FakeQuery(self._rows)


def test_pick_distractors_insufficient_even_after_relaxing():
    """
    Topic giả lập chỉ có 2 vocab (ngoài đáp án đúng) -> kể cả sau khi nới lỏng hết
    3 tầng vẫn không đủ k=3 -> pick_distractors phải raise ValueError, KHÔNG âm thầm
    trả về ít hơn k.
    """
    target = _FakeVocab(id="TARGET", topic=Topic.number, vocab_level=1)
    only_two = [
        _FakeVocab(id="A", topic=Topic.number, vocab_level=1),
        _FakeVocab(id="B", topic=Topic.number, vocab_level=1),
    ]
    fake_session = _FakeSession(only_two)

    with pytest.raises(ValueError):
        pick_distractors(target_vocab=target, db_session=fake_session, k=3)


# ==============================================================================
# save_session_result — lưu ScoreResult vào DB thật (fixture tối thiểu, rollback)
# ==============================================================================


@pytest.fixture
def create_minimal_session_chain(db_session):
    """
    Dựng chuỗi tối thiểu Therapist -> Patient -> TherapyPlan -> ExerciseAssignment
    (gắn 1 Exercise naming CÓ THẬT) -> ExerciseSession, flush để lấy UUID thật, yield
    session_id. Sau test: rollback để xoá sạch toàn bộ fixture giả, KHÔNG để lại rác.
    """
    uniq = uuid.uuid4().hex[:8]

    therapist = Therapist(
        full_name="TEST_THERAPIST_DO_NOT_USE",
        email=f"test_therapist_{uniq}@example.invalid",
        password_hash="x",
        license_no="TEST-LICENSE",
    )
    patient = Patient(
        full_name="TEST_PATIENT_DO_NOT_USE",
        email=f"test_patient_{uniq}@example.invalid",
        password_hash="x",
        date_of_birth=date(1980, 1, 1),
        gender=Gender.male,
    )
    db_session.add_all([therapist, patient])
    db_session.flush()

    plan = TherapyPlan(
        patient_id=patient.id,
        therapist_id=therapist.id,
        title="TEST_PLAN_DO_NOT_USE",
        start_date=date.today(),
    )
    db_session.add(plan)
    db_session.flush()

    naming_exercise = (
        db_session.query(Exercise)
        .filter(Exercise.exercise_type == ExerciseType.naming)
        .first()
    )
    assert naming_exercise is not None, "Không tìm thấy bài naming — đã seed chưa?"

    assignment = ExerciseAssignment(
        plan_id=plan.id,
        exercise_id=naming_exercise.id,
        order_index=1,
    )
    db_session.add(assignment)
    db_session.flush()

    ex_session = ExerciseSession(
        assignment_id=assignment.id,
        patient_id=patient.id,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(ex_session)
    db_session.flush()

    try:
        yield ex_session.id
    finally:
        db_session.rollback()


def test_save_session_result_naming(db_session, create_minimal_session_chain):
    """Lưu 1 ScoreResult naming hợp lệ vào session_results, query lại đối chiếu."""
    session_id = create_minimal_session_chain

    naming_exercise = (
        db_session.query(Exercise)
        .filter(Exercise.exercise_type == ExerciseType.naming)
        .first()
    )
    scoring_ex = build_scoring_exercise(naming_exercise, db_session)

    # transcript = canonical_word -> chắc chắn đúng đáp án -> ScoreResult hợp lệ
    score_result = score(
        scoring_ex,
        transcript=scoring_ex.canonical_word,
        audio_duration=scoring_ex.duration_expected or 2.0,
        asr_confidence=0.9,
    )

    row = save_session_result(db_session, session_id=session_id, score_result=score_result)
    db_session.flush()

    saved = db_session.query(SessionResult).filter(SessionResult.id == row.id).first()
    assert saved is not None
    assert saved.session_id == session_id
    assert saved.score == pytest.approx(score_result.score, abs=0.01)
    assert saved.result == ResultLabel(score_result.result)
    assert isinstance(saved.components, dict) and len(saved.components) > 0


def test_save_session_result_invalid_result_raises(db_session, create_minimal_session_chain):
    """result không nằm trong ResultLabel -> raise ValueError, không lưu bừa."""
    session_id = create_minimal_session_chain

    naming_exercise = (
        db_session.query(Exercise)
        .filter(Exercise.exercise_type == ExerciseType.naming)
        .first()
    )
    scoring_ex = build_scoring_exercise(naming_exercise, db_session)
    score_result = score(
        scoring_ex,
        transcript=scoring_ex.canonical_word,
        audio_duration=2.0,
        asr_confidence=0.9,
    )
    # ép result thành chuỗi không tồn tại trong enum
    score_result.result = "một_chuỗi_không_tồn_tại_trong_enum"

    with pytest.raises(ValueError):
        save_session_result(db_session, session_id=session_id, score_result=score_result)
