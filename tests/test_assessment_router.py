"""
Test router assessment qua HTTP thật (FastAPI TestClient).

LƯU Ý: register COMMIT thật vào DB. Fixture cleanup_test_users xoá mọi User test
(email 'test_%@example.com') sau mỗi test — phải xoá TherapyPlan trước (FK
therapy_plans.patient_id KHÔNG cascade), còn Assessment/AssessmentResult tự cascade
theo FK ondelete CASCADE khi patient bị xoá.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.therapy import TherapyPlan
from app.models.user import User

client = TestClient(app)


def _unique_email() -> str:
    return f"test_{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture
def cleanup_test_users():
    """Yield rồi xoá sạch user test sau mỗi test (rollback trạng thái DB)."""
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
                    db.delete(u)  # assessments/results cascade theo FK
                db.commit()
        finally:
            db.close()


def _patient_payload(email: str, **extra) -> dict:
    payload = {
        "full_name": "TEST_PATIENT_DO_NOT_USE",
        "email": email,
        "password": "secret123",
        "phone_number": "0900000000",
        "date_of_birth": "1980-01-01",
        "gender": "male",
        "aphasia_type": "broca",
        "severity_level": "mild",
        "hospital_name": "BV Test",
        "referring_doctor_name": "BS Test",
    }
    payload.update(extra)
    return payload


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_register_with_baseline_scores_creates_assessment(cleanup_test_users):
    email = _unique_email()
    payload = _patient_payload(
        email,
        accuracy_score=80.0,
        completion_score=65.5,
        fluency_score=42.0,
    )
    reg = client.post("/auth/register/patient", json=payload)
    assert reg.status_code == 201, reg.text
    token = reg.json()["access_token"]

    resp = client.get("/patients/me/initial-assessment", headers=_auth_header(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # 4 field chẩn đoán từ hồ sơ Patient
    assert data["aphasia_type"] == "broca"
    assert data["severity_level"] == "mild"
    assert data["hospital_name"] == "BV Test"
    assert data["referring_doctor_name"] == "BS Test"
    # 3 chỉ số khớp đúng lúc đăng ký
    assert data["accuracy_score"] == 80.0
    assert data["completion_score"] == 65.5
    assert data["fluency_score"] == 42.0


def test_register_without_baseline_scores_returns_nulls(cleanup_test_users):
    email = _unique_email()
    reg = client.post("/auth/register/patient", json=_patient_payload(email))
    assert reg.status_code == 201, reg.text
    token = reg.json()["access_token"]

    resp = client.get("/patients/me/initial-assessment", headers=_auth_header(token))
    # KHÔNG có assessment nào -> vẫn 200, 3 field điểm đều None (không phải 404)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["accuracy_score"] is None
    assert data["completion_score"] is None
    assert data["fluency_score"] is None
    # 4 field chẩn đoán vẫn trả về bình thường
    assert data["aphasia_type"] == "broca"
