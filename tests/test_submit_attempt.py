"""
Test POST /assignments/{id}/submit — nộp bài thật + LƯU session_results.

- Đăng ký patient thật qua API (tự tạo plan + 30 assignment - Bước 8).
- Reuse _make_wav từ test_audio_service (KHÔNG viết lại).
- Monkeypatch ASR stub để "giả lập đúng đáp án" (stub trả chuỗi cố định, ta ép nó trả
  canonical_word của bài đang chấm).
- Cleanup: xoá plan (cascade sessions/results) + user test sau mỗi test.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.content import Exercise
from app.models.enums import ExerciseType
from app.models.therapy import (
    ExerciseAssignment,
    ExerciseSession,
    SessionResult,
    TherapyPlan,
)
from app.models.user import User
from app.services import asr_service
from tests.test_audio_service import _make_wav

client = TestClient(app)


# ── Cleanup fixture ───────────────────────────────────────────────────────────
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
                # Xoá plan trước -> cascade assignments -> sessions -> results (DB ondelete CASCADE)
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


# ── Helpers ───────────────────────────────────────────────────────────────────
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


def _first_naming_assignment(email: str):
    """Trả về (assignment_id, canonical_word) của 1 bài naming trong plan của patient."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assignment = (
            db.query(ExerciseAssignment)
            .join(TherapyPlan, ExerciseAssignment.plan_id == TherapyPlan.id)
            .join(Exercise, ExerciseAssignment.exercise_id == Exercise.id)
            .filter(
                TherapyPlan.patient_id == user.id,
                Exercise.exercise_type == ExerciseType.naming,
            )
            .first()
        )
        assert assignment is not None
        canonical_word = assignment.exercise.target_vocab.canonical_word
        return assignment.id, canonical_word
    finally:
        db.close()


# ── Tests ─────────────────────────────────────────────────────────────────────
def test_submit_attempt_naming_success(cleanup_test_data, monkeypatch):
    reg = _register_patient()
    token = reg["access_token"]
    assignment_id, canonical_word = _first_naming_assignment(reg["email"])

    # ASR "giả lập đúng đáp án": ép stub trả canonical_word của bài này
    monkeypatch.setattr(
        asr_service,
        "transcribe_audio",
        lambda wav_bytes: {"transcript": canonical_word, "confidence": 0.9},
    )

    wav = _make_wav(duration_s=2.0, amplitude=8000)
    resp = client.post(
        f"/assignments/{assignment_id}/submit",
        files={"audio_file": ("test.wav", wav, "audio/wav")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["result"] == "pass"
    assert data["score"] >= 70
    assert data["is_final"] is True
    assert data["attempt_number"] == 1
    assert isinstance(data["feedback_messages"], list)


def test_submit_attempt_wrong_patient_forbidden(cleanup_test_data, monkeypatch):
    # Patient A có bài; patient B cố nộp bài của A
    reg_a = _register_patient()
    assignment_id_a, _ = _first_naming_assignment(reg_a["email"])

    reg_b = _register_patient()
    token_b = reg_b["access_token"]

    monkeypatch.setattr(
        asr_service,
        "transcribe_audio",
        lambda wav_bytes: {"transcript": "cái kéo", "confidence": 0.9},
    )

    wav = _make_wav(duration_s=2.0, amplitude=8000)
    resp = client.post(
        f"/assignments/{assignment_id_a}/submit",
        files={"audio_file": ("test.wav", wav, "audio/wav")},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 403, resp.text


def test_submit_attempt_persists_to_db(cleanup_test_data, monkeypatch):
    reg = _register_patient()
    token = reg["access_token"]
    assignment_id, canonical_word = _first_naming_assignment(reg["email"])

    monkeypatch.setattr(
        asr_service,
        "transcribe_audio",
        lambda wav_bytes: {"transcript": canonical_word, "confidence": 0.9},
    )

    wav = _make_wav(duration_s=2.0, amplitude=8000)
    resp = client.post(
        f"/assignments/{assignment_id}/submit",
        files={"audio_file": ("test.wav", wav, "audio/wav")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    # Query THẲNG vào DB xác nhận có đúng 1 SessionResult cho assignment này
    db = SessionLocal()
    try:
        rows = (
            db.query(SessionResult)
            .join(ExerciseSession, SessionResult.session_id == ExerciseSession.id)
            .filter(ExerciseSession.assignment_id == assignment_id)
            .all()
        )
        assert len(rows) == 1, f"Kỳ vọng 1 SessionResult, thực tế {len(rows)}"
        assert rows[0].transcript is not None
        # session phải đã graded (pass -> final)
        session = (
            db.query(ExerciseSession)
            .filter(ExerciseSession.assignment_id == assignment_id)
            .first()
        )
        assert session.status.value == "graded"
        assert session.completed_at is not None
    finally:
        db.close()
