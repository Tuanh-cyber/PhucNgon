"""
Test cho:
  1. attempt_to_metrics()  — hàm SINGLE-SOURCE map 1 lượt -> 3 tiêu chí (unit, không DB).
  2. build_feedback()      — câu nhận xét có phân loại từ components + result (unit).
  3. Response POST /assignments/{id}/submit — đủ 3 tiêu chí + feedback (HTTP, có DB).

Unit test dùng dữ liệu components giả lập đúng hình dạng scoring_service sinh ra cho
từng loại bài (NAM/CMD/SEN/invalid) — KHÔNG gọi scoring engine, chỉ kiểm tra tầng map.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.content import Exercise
from app.models.enums import ExerciseType
from app.models.therapy import ExerciseAssignment, TherapyPlan
from app.models.user import User
from app.services import asr_service
from app.services.session_service import INVALID_INPUT_MESSAGES, build_feedback
from app.services.stats_service import attempt_to_metrics
from tests.test_audio_service import _make_wav

client = TestClient(app)


# ══════════════════════════════════════════════════════════════════════════════
# 1. attempt_to_metrics — unit
# ══════════════════════════════════════════════════════════════════════════════

# completion_score CẤP-1-LƯỢT = ĐỘ PHỦ NỘI DUNG (recall), KHÔNG phải "bài có kết thúc".

def test_metrics_naming_coverage_binary():
    # NAM: completion = components["keyword"] = keyword_match() -> 0/100.
    ok = attempt_to_metrics(85.0, {"keyword": 100, "text_similarity": 90, "fluency": 70}, "pass")
    assert ok == {"accuracy_score": 85.0, "completion_score": 100, "fluency_score": 70}

    miss = attempt_to_metrics(20.0, {"keyword": 0, "text_similarity": 15, "fluency": 70}, "retry")
    assert miss["completion_score"] == 0            # không gọi được tên -> phủ 0%
    assert miss["accuracy_score"] == 20.0           # accuracy vẫn = score


def test_metrics_sentence_coverage_fractional():
    # SEN: completion = components["keyword"] = keyword_coverage() -> điểm LẺ.
    # vd nói được 2/3 từ khuyết -> ~66.67 (KHÔNG còn binary theo is_final).
    comp = {"keyword": 66.67, "order_score": 80, "fluency": 55}
    m = attempt_to_metrics(60.0, comp, "near")      # "near" = chưa đạt nhưng vẫn đo phủ
    assert m["accuracy_score"] == 60.0
    assert m["fluency_score"] == 55
    assert m["completion_score"] == pytest.approx(66.67)


def test_metrics_recognition_touch():
    # CMD recognition (touch): score None, chỉ binary_touch -> accuracy/fluency None.
    # completion = 100 nếu chọn đúng (correct), 0 nếu chọn sai (incorrect).
    ok = attempt_to_metrics(None, {"binary_touch": True}, "correct")
    assert ok["accuracy_score"] is None
    assert ok["fluency_score"] is None
    assert ok["completion_score"] == 100.0

    wrong = attempt_to_metrics(None, {"binary_touch": False}, "incorrect")
    assert wrong["completion_score"] == 0.0         # chọn sai -> phủ 0% (KHÁC bản cũ)


def test_metrics_invalid_input_none():
    # input rác: components {"error":...} -> KHÔNG đo được độ phủ -> None (KHÁC bản cũ = 0.0).
    m = attempt_to_metrics(None, {"error": "AUDIO_TOO_SHORT"}, "invalid")
    assert m == {
        "accuracy_score": None,
        "completion_score": None,
        "fluency_score": None,
    }


def test_metrics_keyword_coverage_key_priority():
    # Dự phòng: nếu sau này SEN tách key riêng "keyword_coverage", ưu tiên dùng nó.
    m = attempt_to_metrics(70.0, {"keyword_coverage": 33.33, "keyword": 100, "fluency": 80}, "near")
    assert m["completion_score"] == pytest.approx(33.33)


def test_metrics_accuracy_fluency_unchanged():
    # accuracy = score; fluency = components["fluency"] — GIỮ NGUYÊN, là field mà
    # compute_patient_stats trung bình (single source cho 2 tiêu chí này).
    comp = {"keyword": 100, "text_similarity": 90, "fluency": 88}
    m = attempt_to_metrics(77.0, comp, "pass")
    assert m["accuracy_score"] == 77.0
    assert m["fluency_score"] == comp["fluency"]


# ══════════════════════════════════════════════════════════════════════════════
# 2. build_feedback — unit
# ══════════════════════════════════════════════════════════════════════════════

def test_feedback_naming_correct_ok():
    fb = build_feedback("naming", {"keyword": 100, "text_similarity": 95, "fluency": 90}, "cái kéo", "pass")
    assert {"type": "ok", "text": "Đã gọi đúng tên"} in fb
    assert all(item["type"] in ("ok", "warn") for item in fb)


def test_feedback_naming_wrong_warn():
    fb = build_feedback("naming", {"keyword": 0, "text_similarity": 20, "fluency": 90}, "con chó", "retry")
    texts = [i["text"] for i in fb]
    assert "Chưa nhận diện được từ đã nói" in texts
    assert all(i["type"] == "warn" for i in fb)


def test_feedback_naming_classifier_missing():
    fb = build_feedback(
        "naming",
        {"keyword": 100, "text_similarity": 95, "classifier_present": 0, "fluency": 90},
        "kéo", "pass",
    )
    texts = [i["text"] for i in fb]
    assert "Đã gọi đúng tên" in texts
    assert any("loại từ" in t for t in texts)


def test_feedback_sentence_missing_and_present():
    fb = build_feedback(
        "sentence_building",
        {"order_score": 50, "fluency": 90, "missing_words": ["khoai lang"]},
        "tôi muốn ăn", "near",
    )
    texts = [i["text"] for i in fb]
    assert "Còn thiếu từ 'khoai lang'" in texts

    fb2 = build_feedback(
        "sentence_building",
        {"order_score": 100, "fluency": 90, "missing_words": ["khoai lang"]},
        "tôi muốn ăn khoai lang", "pass",
    )
    assert {"type": "ok", "text": "Đã nói đúng từ 'khoai lang'"} in fb2


def test_feedback_invalid_uses_friendly_message():
    for code, friendly in INVALID_INPUT_MESSAGES.items():
        fb = build_feedback("naming", {"error": code}, "", "invalid")
        assert fb == [{"type": "warn", "text": friendly}]


def test_feedback_fluency_low_hint():
    fb = build_feedback("naming", {"keyword": 100, "text_similarity": 95, "fluency": 30}, "cái kéo", "pass")
    texts = [i["text"] for i in fb]
    assert any("đều nhịp" in t for t in texts)


def test_feedback_recognition_no_speech_comment():
    # CMD recognition: components binary_touch -> không nhận xét phát âm (list rỗng).
    assert build_feedback("command_identification", {"binary_touch": True}, "", "correct") == []


# ══════════════════════════════════════════════════════════════════════════════
# 3. Response submit — HTTP integration
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def cleanup_test_data():
    try:
        yield
    finally:
        db = SessionLocal()
        try:
            users = db.query(User).filter(User.email.like("test_%@example.com")).all()
            user_ids = [u.id for u in users]
            if user_ids:
                plans = (
                    db.query(TherapyPlan).filter(TherapyPlan.patient_id.in_(user_ids)).all()
                )
                for p in plans:
                    db.delete(p)
                db.flush()
                for u in users:
                    db.delete(u)
                db.commit()
        finally:
            db.close()


def _register_patient() -> dict:
    email = f"test_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post("/auth/register/patient", json={
        "full_name": "TEST_PATIENT_DO_NOT_USE", "email": email, "password": "secret123",
        "date_of_birth": "1980-01-01", "gender": "male", "severity_level": "Nặng"})
    assert resp.status_code == 201, resp.text
    data = resp.json()
    data["email"] = email
    return data


def _first_naming(email: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        a = (
            db.query(ExerciseAssignment)
            .join(TherapyPlan, ExerciseAssignment.plan_id == TherapyPlan.id)
            .join(Exercise, ExerciseAssignment.exercise_id == Exercise.id)
            .filter(
                TherapyPlan.patient_id == user.id,
                Exercise.exercise_type == ExerciseType.naming,
            )
            .first()
        )
        return a.id, a.exercise.target_vocab.canonical_word
    finally:
        db.close()


def test_submit_response_has_metrics_and_feedback(cleanup_test_data, monkeypatch):
    reg = _register_patient()
    token = reg["access_token"]
    assignment_id, word = _first_naming(reg["email"])

    monkeypatch.setattr(
        asr_service, "transcribe_audio",
        lambda wav: {"transcript": word, "confidence": 0.9},
    )
    wav = _make_wav(duration_s=2.0, amplitude=8000)
    resp = client.post(
        f"/assignments/{assignment_id}/submit",
        files={"audio_file": ("t.wav", wav, "audio/wav")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # đủ 3 tiêu chí
    assert "accuracy_score" in data and "completion_score" in data and "fluency_score" in data
    # naming đúng -> pass (final): accuracy = score, completion = 100
    assert data["result"] == "pass"
    assert data["accuracy_score"] == data["score"]
    assert data["completion_score"] == 100.0
    assert data["fluency_score"] is not None

    # feedback: list các object {type, text}; feedback_messages = list text tương ứng
    assert isinstance(data["feedback"], list) and len(data["feedback"]) >= 1
    for item in data["feedback"]:
        assert item["type"] in ("ok", "warn")
        assert isinstance(item["text"], str) and item["text"]
    assert data["feedback_messages"] == [i["text"] for i in data["feedback"]]
    assert any(i["type"] == "ok" for i in data["feedback"])  # gọi đúng tên -> có "ok"
