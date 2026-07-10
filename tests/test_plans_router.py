"""
Test router plans qua HTTP thật (FastAPI TestClient).

Đăng ký patient qua API (COMMIT thật + tự tạo plan) rồi gọi GET /plans/me/today bằng token.
Cleanup: xoá plan + user test sau mỗi test, KHÔNG để lại rác trong DB thật.
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
def cleanup_test_data():
    """Yield rồi xoá plan + user test (email 'test_%@example.com') sau test."""
    try:
        yield
    finally:
        db = SessionLocal()
        try:
            users = db.query(User).filter(User.email.like("test_%@example.com")).all()
            user_ids = [u.id for u in users]
            if user_ids:
                # Xoá plan trước (cascade assignments qua FK ondelete CASCADE),
                # rồi mới xoá user (patients.id -> users.id ondelete CASCADE).
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
        "phone_number": f"09{int(uuid.uuid4().hex[:8], 16) % 10**8:08d}",  # phone BẮT BUỘC (Mô hình A)
        "date_of_birth": "1980-01-01",
        "gender": "male",
        "severity_level": "Nặng",
    }
    resp = client.post("/auth/register/patient", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_get_today_plan_after_registration(cleanup_test_data):
    token = _register_patient()["access_token"]
    resp = client.get(
        "/plans/me/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["plan_id"]
    types = {e["exercise_type"] for e in data["exercises"]}
    assert types == {"naming", "command_identification", "sentence_building"}
    assert len(data["exercises"]) == 3

    # Vừa đăng ký, chưa làm bài nào -> 0% cho cả 3 nhóm
    for e in data["exercises"]:
        assert e["completed_count"] == 0
        assert e["completion_percent"] == 0
        assert e["total_assigned"] > 0
