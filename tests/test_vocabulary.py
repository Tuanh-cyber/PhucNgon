"""
Test GET /vocabulary — danh sách từ vựng cho flashcard.

Dùng lại pattern đăng ký patient thật (tự tạo qua API) + cleanup như các test khác.
Vocab đọc từ DB đã seed -> kỳ vọng 90 từ.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.therapy import TherapyPlan
from app.models.user import User

client = TestClient(app)


@pytest.fixture
def cleanup_test_users():
    try:
        yield
    finally:
        db = SessionLocal()
        try:
            users = db.query(User).filter(User.email.like("test_%@example.com")).all()
            user_ids = [u.id for u in users]
            if user_ids:
                # Xóa plan (+ assignment cascade) trước, tránh FK chặn khi xóa user.
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


def _register_patient() -> str:
    email = f"test_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/auth/register/patient",
        json={
            "full_name": "TEST_PATIENT_DO_NOT_USE",
            "email": email,
            "password": "secret123",
            "phone_number": f"09{int(uuid.uuid4().hex[:8], 16) % 10**8:08d}",  # phone BẮT BUỘC (Mô hình A)
            "date_of_birth": "1980-01-01",
            "gender": "male",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_vocabulary_requires_auth():
    resp = client.get("/vocabulary")
    assert resp.status_code == 401


def test_vocabulary_returns_all_90(cleanup_test_users):
    token = _register_patient()
    resp = client.get("/vocabulary", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 90, f"kỳ vọng 90 từ, nhận {len(data)}"

    # Mỗi phần tử có đủ field + kiểu đúng
    item = data[0]
    assert set(item.keys()) == {
        "vocab_id",
        "word",
        "topic",
        "word_type",
        "image_url",
        "audio_url",
    }
    assert item["word_type"] in ("noun", "verb", "adjective")

    # Có ít nhất 1 từ có image_url và 1 từ có audio_url (media đã seed vào repo)
    assert any(v["image_url"] for v in data), "không từ nào có image_url"
    assert any(v["audio_url"] for v in data), "không từ nào có audio_url"

    # URL (nếu có) đúng prefix static
    for v in data:
        if v["image_url"]:
            assert v["image_url"].startswith("/static/pictures/")
        if v["audio_url"]:
            assert v["audio_url"].startswith("/static/vocab-audio/")


def test_vocabulary_filter_by_topic(cleanup_test_users):
    token = _register_patient()
    resp = client.get("/vocabulary?topic=food_drink", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) > 0
    assert all(v["topic"] == "food_drink" for v in data)
    # Lọc theo topic -> ít hơn tổng 90
    assert len(data) < 90


def test_vocabulary_invalid_topic_422(cleanup_test_users):
    token = _register_patient()
    resp = client.get("/vocabulary?topic=not_a_topic", headers=_auth(token))
    assert resp.status_code == 422
