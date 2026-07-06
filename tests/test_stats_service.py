"""
Test compute_patient_stats() — chỉ số tính tự động từ SessionResult thật.

- Đăng ký patient thật qua API (tự tạo plan + assignment - Bước 8).
- Reuse _make_wav từ test_audio_service + monkeypatch ASR (KHÔNG viết lại).
- Gọi submit_attempt() trực tiếp ở tầng service để tạo dữ liệu thật rồi tính stats.
- Cleanup: xoá plan (cascade sessions/results) + user test sau mỗi test.
"""

import uuid

import pytest

from app.core.database import SessionLocal
from app.main import app  # noqa: F401 — đảm bảo model/router đã nạp
from app.models.content import Exercise
from app.models.enums import ExerciseType
from app.models.therapy import ExerciseAssignment, TherapyPlan
from app.models.user import Patient, User
from app.services import asr_service
from app.services.session_service import submit_attempt
from app.services.stats_service import compute_patient_stats
from fastapi.testclient import TestClient
from tests.test_audio_service import _make_wav

client = TestClient(app)


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
                    db.query(TherapyPlan)
                    .filter(TherapyPlan.patient_id.in_(user_ids))
                    .all()
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
    payload = {
        "full_name": "TEST_PATIENT_DO_NOT_USE",
        "email": email,
        "password": "secret123",
        "date_of_birth": "1980-01-01",
        "gender": "male",
        "severity_level": "Nặng",
    }
    resp = client.post("/auth/register/patient", json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    data["email"] = email
    return data


def test_compute_stats_no_sessions_returns_nulls(cleanup_test_data):
    """Patient mới đăng ký, chưa làm bài nào -> cả 3 chỉ số là None."""
    reg = _register_patient()
    db = SessionLocal()
    try:
        patient = db.query(User).filter(User.email == reg["email"]).first()
        stats = compute_patient_stats(db, patient.id)
        assert stats == {
            "accuracy_score": None,
            "completion_score": None,
            "fluency_score": None,
        }
    finally:
        db.close()


def test_compute_stats_after_one_correct_attempt(cleanup_test_data, monkeypatch):
    """Sau 1 bài naming đúng đáp án -> accuracy_score > 0 và completion_score > 0."""
    reg = _register_patient()
    db = SessionLocal()
    try:
        patient = db.query(Patient).filter(Patient.email == reg["email"]).first()
        assignment = (
            db.query(ExerciseAssignment)
            .join(TherapyPlan, ExerciseAssignment.plan_id == TherapyPlan.id)
            .join(Exercise, ExerciseAssignment.exercise_id == Exercise.id)
            .filter(
                TherapyPlan.patient_id == patient.id,
                Exercise.exercise_type == ExerciseType.naming,
            )
            .first()
        )
        assert assignment is not None
        canonical_word = assignment.exercise.target_vocab.canonical_word

        # ASR "giả lập đúng đáp án": ép stub trả canonical_word của bài này.
        monkeypatch.setattr(
            asr_service,
            "transcribe_audio",
            lambda wav_bytes: {"transcript": canonical_word, "confidence": 0.9},
        )

        wav = _make_wav(duration_s=2.0, amplitude=8000)
        saved, _, _ = submit_attempt(db, patient, assignment.id, wav_bytes=wav)
        assert saved.result.value == "pass"  # naming đúng -> pass -> session graded

        stats = compute_patient_stats(db, patient.id)
        assert stats["accuracy_score"] is not None
        assert stats["accuracy_score"] > 0
        assert stats["completion_score"] is not None
        assert stats["completion_score"] > 0
    finally:
        db.close()
