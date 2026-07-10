"""
Test GET /patients/me/stats — chỉ số tính tự động (qua HTTP thật, TestClient).

Cleanup: xoá plan (cascade) + user test sau mỗi test.
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


def test_get_my_stats_after_registration_no_data(cleanup_test_users):
    """Đăng ký mới, chưa làm bài -> GET /patients/me/stats trả cả 3 field None (200, không 404)."""
    reg = _register_patient()
    token = reg["access_token"]

    resp = client.get(
        "/patients/me/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["accuracy_score"] is None
    assert data["completion_score"] is None
    assert data["fluency_score"] is None


def test_get_my_stats_requires_patient_role(cleanup_test_users):
    """Therapist gọi endpoint bệnh nhân -> 403."""
    email = f"test_{uuid.uuid4().hex[:10]}@example.com"
    reg = client.post(
        "/auth/register/therapist",
        json={
            "full_name": "TEST_THERAPIST_DO_NOT_USE",
            "email": email,
            "password": "secret123",
            "phone_number": f"09{int(uuid.uuid4().hex[:8], 16) % 10**8:08d}",  # phone BẮT BUỘC (Mô hình A)
            "license_no": "LIC-TEST-001",
        },
    )
    assert reg.status_code == 201, reg.text
    token = reg.json()["access_token"]

    resp = client.get(
        "/patients/me/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text
