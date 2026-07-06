"""
Test router auth qua HTTP thật (FastAPI TestClient).

LƯU Ý: các endpoint register/login COMMIT thật vào DB, nên không thể rollback session
của test. Thay vào đó fixture cleanup_test_users xoá mọi User có email 'test_%@example.com'
sau mỗi test (FK ondelete CASCADE tự xoá dòng patient/therapist con).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.therapy import TherapyPlan
from app.models.user import Profile, User

client = TestClient(app)


def _unique_email() -> str:
    return f"test_{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture
def cleanup_test_users():
    """
    Yield rồi xoá sạch mọi user test (email 'test_%@example.com') sau test.

    Đăng ký patient giờ tự tạo TherapyPlan (auto-provisioning), nên phải xoá plan TRƯỚC
    (cascade assignments qua FK ondelete CASCADE) rồi mới xoá user — nếu không sẽ vướng
    FK therapy_plans.patient_id.
    """
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


def _patient_payload(email: str) -> dict:
    return {
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


def test_register_patient_success(cleanup_test_users):
    email = _unique_email()
    resp = client.post("/auth/register/patient", json=_patient_payload(email))
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["access_token"]
    assert data["token_type"] == "bearer"
    assert data["role"] == "patient"


def test_register_duplicate_email_fails(cleanup_test_users):
    email = _unique_email()
    r1 = client.post("/auth/register/patient", json=_patient_payload(email))
    assert r1.status_code == 201, r1.text
    r2 = client.post("/auth/register/patient", json=_patient_payload(email))
    assert r2.status_code == 409


def test_login_wrong_password_fails(cleanup_test_users):
    email = _unique_email()
    client.post("/auth/register/patient", json=_patient_payload(email))
    resp = client.post("/auth/login", json={"email": email, "password": "WRONG_password"})
    assert resp.status_code == 401


def test_login_success_returns_token(cleanup_test_users):
    email = _unique_email()
    client.post("/auth/register/patient", json=_patient_payload(email))
    resp = client.post("/auth/login", json={"email": email, "password": "secret123"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["access_token"]
    assert data["role"] == "patient"


def test_get_me_returns_user_info(cleanup_test_users):
    email = _unique_email()
    reg = client.post("/auth/register/patient", json=_patient_payload(email))
    token = reg.json()["access_token"]

    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["email"] == email
    assert data["full_name"] == "TEST_PATIENT_DO_NOT_USE"
    assert data["role"] == "patient"
    assert data["user_id"]


def test_get_me_without_token_401():
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_register_with_address_creates_profile(cleanup_test_users):
    """Đăng ký kèm address -> tạo 1 Profile gắn user_id, address khớp đúng."""
    email = _unique_email()
    payload = _patient_payload(email)
    payload["address"] = "123 Đường ABC, Quận 1, TP.HCM"

    resp = client.post("/auth/register/patient", json=payload)
    assert resp.status_code == 201, resp.text

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assert user is not None
        profile = db.query(Profile).filter(Profile.user_id == user.id).first()
        assert profile is not None
        assert profile.address == "123 Đường ABC, Quận 1, TP.HCM"
    finally:
        db.close()


def test_register_without_address_no_profile_created(cleanup_test_users):
    """Đăng ký KHÔNG kèm address/caregiver_phone -> KHÔNG tạo Profile nào cho user này."""
    email = _unique_email()
    payload = _patient_payload(email)  # không có key "address"/"caregiver_phone"

    resp = client.post("/auth/register/patient", json=payload)
    assert resp.status_code == 201, resp.text

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assert user is not None
        profile = db.query(Profile).filter(Profile.user_id == user.id).first()
        assert profile is None
    finally:
        db.close()


def test_register_with_caregiver_phone_sets_emergency_contact(cleanup_test_users):
    """Đăng ký kèm caregiver_phone (không có address) -> Profile.emergency_contact khớp,
    address = None."""
    email = _unique_email()
    payload = _patient_payload(email)
    payload["caregiver_phone"] = "0987654321"

    resp = client.post("/auth/register/patient", json=payload)
    assert resp.status_code == 201, resp.text

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        profile = db.query(Profile).filter(Profile.user_id == user.id).first()
        assert profile is not None
        assert profile.emergency_contact == "0987654321"
        assert profile.address is None
    finally:
        db.close()
