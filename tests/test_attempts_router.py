"""
Test router attempts qua HTTP thật (FastAPI TestClient — không cần chạy server).

Chỉ test GET /exercises/{id} ở bước này. POST /attempt-preview cần file WAV thật,
để test tay qua Postman sau.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.content import Exercise
from app.models.enums import ExerciseType

client = TestClient(app)


@pytest.fixture
def naming_exercise_id():
    """Lấy id 1 bài naming THẬT từ DB đã seed."""
    db = SessionLocal()
    try:
        ex = (
            db.query(Exercise)
            .filter(Exercise.exercise_type == ExerciseType.naming)
            .first()
        )
        assert ex is not None, "Không tìm thấy bài naming — đã seed chưa?"
        return str(ex.id)
    finally:
        db.close()


def test_get_exercise_info_success(naming_exercise_id):
    """GET exercise thật -> 200, KHÔNG lộ đáp án (canonical_word/accepted_answers)."""
    resp = client.get(f"/exercises/{naming_exercise_id}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["exercise_id"] == naming_exercise_id
    assert data["exercise_type"] == "naming"
    assert "topic" in data
    assert "vocab_level" in data

    # Không được lộ đáp án đúng ra JSON
    assert "canonical_word" not in data
    assert "accepted_answers" not in data
    assert "full_sentence" not in data


def test_get_exercise_info_not_found():
    """GET với UUID không tồn tại -> 404."""
    random_id = uuid.uuid4()
    resp = client.get(f"/exercises/{random_id}")
    assert resp.status_code == 404
