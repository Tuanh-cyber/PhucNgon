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
        "phone_number": f"09{int(uuid.uuid4().hex[:8], 16) % 10**8:08d}",  # unique (chống trùng số)
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


# ── Phone bệnh nhân BẮT BUỘC (Mô hình A) ─────────────────────────────────────

def test_register_patient_missing_phone_422(cleanup_test_users):
    """Đăng ký bệnh nhân THIẾU phone_number -> 422 (field bắt buộc)."""
    payload = _patient_payload(_unique_email())
    del payload["phone_number"]
    resp = client.post("/auth/register/patient", json=payload)
    assert resp.status_code == 422


def test_register_patient_garbage_phone_422(cleanup_test_users):
    """Phone rác (chữ / quá ngắn) -> 422 với message tiếng Việt."""
    for bad in ("abc", "123", "09x9y8z7"):
        payload = _patient_payload(_unique_email())
        payload["phone_number"] = bad
        resp = client.post("/auth/register/patient", json=payload)
        assert resp.status_code == 422, f"phone {bad!r} phải bị 422"


def test_register_patient_phone_normalized_stored(cleanup_test_users):
    """Nhập '+84 91 234 5678' -> DB lưu DẠNG CHUẨN '0912345678'."""
    email = _unique_email()
    suffix = f"{int(uuid.uuid4().hex[:8], 16) % 10**8:08d}"
    payload = _patient_payload(email)
    payload["phone_number"] = f"+84 9{suffix[0]} {suffix[1:4]} {suffix[4:]}"
    resp = client.post("/auth/register/patient", json=payload)
    assert resp.status_code == 201, resp.text

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).one()
        assert u.phone_number == f"09{suffix}"  # đã chuẩn hóa, không còn +84/khoảng trắng
    finally:
        db.close()


def test_register_patient_duplicate_phone_409(cleanup_test_users):
    """Số đã có bệnh nhân khác dùng (kể cả khác định dạng thô) -> 409."""
    phone = f"09{int(uuid.uuid4().hex[:8], 16) % 10**8:08d}"
    p1 = _patient_payload(_unique_email())
    p1["phone_number"] = phone
    assert client.post("/auth/register/patient", json=p1).status_code == 201

    p2 = _patient_payload(_unique_email())
    p2["phone_number"] = "+84" + phone[1:]  # khác chuỗi thô, TRÙNG sau chuẩn hóa
    r2 = client.post("/auth/register/patient", json=p2)
    assert r2.status_code == 409
    assert "Số điện thoại đã được đăng ký" in r2.json()["detail"]


def test_register_patient_caregiver_phone_still_optional(cleanup_test_users):
    """caregiver_phone (người thân) vẫn OPTIONAL và không bị ép định dạng."""
    # Không gửi caregiver_phone -> vẫn 201
    assert (
        client.post("/auth/register/patient", json=_patient_payload(_unique_email())).status_code
        == 201
    )
    # Gửi caregiver_phone dạng tự do -> vẫn 201 (không validate như phone bệnh nhân)
    payload = _patient_payload(_unique_email())
    payload["caregiver_phone"] = "0987 654 321 (con trai)"
    assert client.post("/auth/register/patient", json=payload).status_code == 201


# ── POST /auth/change-password ───────────────────────────────────────────────

def test_change_password_full_flow(cleanup_test_users):
    """Đổi thành công -> login mật khẩu MỚI ok, mật khẩu CŨ fail 401."""
    email = _unique_email()
    reg = client.post("/auth/register/patient", json=_patient_payload(email))
    token = reg.json()["access_token"]

    r = client.post(
        "/auth/change-password",
        json={"current_password": "secret123", "new_password": "matkhaumoi456"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert "thành công" in r.json()["message"]

    # Mật khẩu MỚI đăng nhập được
    ok = client.post("/auth/login", json={"email": email, "password": "matkhaumoi456"})
    assert ok.status_code == 200
    # Mật khẩu CŨ bị từ chối
    old = client.post("/auth/login", json={"email": email, "password": "secret123"})
    assert old.status_code == 401


def test_change_password_wrong_current_400(cleanup_test_users):
    """current_password sai -> 400 'Mật khẩu hiện tại không đúng'; mật khẩu KHÔNG đổi."""
    email = _unique_email()
    token = client.post("/auth/register/patient", json=_patient_payload(email)).json()[
        "access_token"
    ]
    r = client.post(
        "/auth/change-password",
        json={"current_password": "saibetrom", "new_password": "matkhaumoi456"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
    assert "Mật khẩu hiện tại không đúng" in r.json()["detail"]
    # Mật khẩu cũ vẫn dùng được (không bị đổi lén)
    assert client.post("/auth/login", json={"email": email, "password": "secret123"}).status_code == 200


def test_change_password_unauthenticated_401():
    r = client.post(
        "/auth/change-password",
        json={"current_password": "x", "new_password": "matkhaumoi456"},
    )
    assert r.status_code == 401


def test_change_password_too_short_422(cleanup_test_users):
    """new_password < 6 ký tự -> 422 (Pydantic min_length)."""
    email = _unique_email()
    token = client.post("/auth/register/patient", json=_patient_payload(email)).json()[
        "access_token"
    ]
    r = client.post(
        "/auth/change-password",
        json={"current_password": "secret123", "new_password": "abc"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422
