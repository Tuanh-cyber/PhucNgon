"""
Test LỊCH HẸN: bác sĩ đặt cho bệnh nhân CỦA MÌNH (mask), bệnh nhân chỉ thấy lịch của mình.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.appointment import Appointment
from app.models.therapy import TherapyPlan
from app.models.user import User

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
                # Xóa appointments trước (FK tới patients/therapists), rồi plans, rồi users.
                db.query(Appointment).filter(
                    Appointment.patient_id.in_(user_ids)
                ).delete(synchronize_session=False)
                for p in (
                    db.query(TherapyPlan).filter(TherapyPlan.patient_id.in_(user_ids)).all()
                ):
                    db.delete(p)
                db.flush()
                for u in users:
                    db.delete(u)
                db.commit()
        finally:
            db.close()


def _unique_phone() -> str:
    return f"09{int(uuid.uuid4().hex[:8], 16) % 10**8:08d}"


def _register_patient() -> dict:
    email = f"test_{uuid.uuid4().hex[:10]}@example.com"
    phone = _unique_phone()
    resp = client.post(
        "/auth/register/patient",
        json={
            "full_name": "TEST_PATIENT_DO_NOT_USE",
            "email": email,
            "password": "secret123",
            "phone_number": phone,
            "date_of_birth": "1980-01-01",
            "gender": "male",
        },
    )
    assert resp.status_code == 201, resp.text
    return {"email": email, "phone": phone, "token": resp.json()["access_token"]}


def _register_therapist(name: str = "TEST_THERAPIST_DO_NOT_USE") -> dict:
    email = f"test_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/auth/register/therapist",
        json={
            "full_name": name,
            "email": email,
            "password": "secret123",
            "license_no": f"LIC-{uuid.uuid4().hex[:6]}",
        },
    )
    assert resp.status_code == 201, resp.text
    return {"email": email, "token": resp.json()["access_token"]}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _patient_id_of(email: str) -> str:
    db = SessionLocal()
    try:
        return str(db.query(User).filter(User.email == email).one().id)
    finally:
        db.close()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _appointment_body(**over) -> dict:
    starts = datetime.now(timezone.utc) + timedelta(days=2)
    body = {
        "starts_at": _iso(starts),
        "ends_at": _iso(starts + timedelta(hours=1)),
        "location": "BV Chợ Rẫy",
        "room": "P.204",
        "note": "Tái khám định kỳ",
    }
    body.update(over)
    return body


def test_create_and_patient_reads_own(cleanup_test_data):
    """Bác sĩ đặt lịch cho bệnh nhân CỦA MÌNH -> patient đọc thấy đúng lịch + doctor_name."""
    ther = _register_therapist(name="BS. Trần Thanh Phúc")
    pat = _register_patient()
    assert (
        client.post(
            "/therapist/patients/claim", json={"phone": pat["phone"]}, headers=_auth(ther["token"])
        ).status_code
        == 200
    )
    pid = _patient_id_of(pat["email"])

    r = client.post(
        f"/therapist/patients/{pid}/appointments",
        json=_appointment_body(),
        headers=_auth(ther["token"]),
    )
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["location"] == "BV Chợ Rẫy"
    assert created["room"] == "P.204"
    assert created["doctor_name"] == "BS. Trần Thanh Phúc"

    # Patient đọc lịch của mình (default window: tháng ±1 — lịch +2 ngày nằm trong)
    lst = client.get("/patients/me/appointments", headers=_auth(pat["token"]))
    assert lst.status_code == 200, lst.text
    items = lst.json()
    assert len(items) == 1
    assert items[0]["appointment_id"] == created["appointment_id"]
    assert items[0]["doctor_name"] == "BS. Trần Thanh Phúc"
    assert items[0]["note"] == "Tái khám định kỳ"


def test_create_for_foreign_patient_404(cleanup_test_data):
    """Bác sĩ đặt cho bệnh nhân KHÔNG thuộc mình (của người khác / tự do) -> 404 (mask)."""
    ther_a, ther_b = _register_therapist(), _register_therapist()
    pat_b, pat_free = _register_patient(), _register_patient()
    assert (
        client.post(
            "/therapist/patients/claim", json={"phone": pat_b["phone"]}, headers=_auth(ther_b["token"])
        ).status_code
        == 200
    )

    for email in (pat_b["email"], pat_free["email"]):
        pid = _patient_id_of(email)
        r = client.post(
            f"/therapist/patients/{pid}/appointments",
            json=_appointment_body(),
            headers=_auth(ther_a["token"]),
        )
        assert r.status_code == 404, f"patient {email} phải bị mask 404"


def test_patient_sees_only_own_appointments(cleanup_test_data):
    """Patient khác KHÔNG thấy lịch của người khác; ends_at <= starts_at -> 422; 401 khi chưa login."""
    ther = _register_therapist()
    pat1, pat2 = _register_patient(), _register_patient()
    assert client.post(
        "/therapist/patients/claim", json={"phone": pat1["phone"]}, headers=_auth(ther["token"])
    ).status_code == 200
    pid1 = _patient_id_of(pat1["email"])

    # ends_at <= starts_at -> 422 (validator schema)
    starts = datetime.now(timezone.utc) + timedelta(days=1)
    bad = _appointment_body(starts_at=_iso(starts), ends_at=_iso(starts))
    assert (
        client.post(
            f"/therapist/patients/{pid1}/appointments", json=bad, headers=_auth(ther["token"])
        ).status_code
        == 422
    )

    # Đặt 1 lịch hợp lệ cho pat1
    assert (
        client.post(
            f"/therapist/patients/{pid1}/appointments",
            json=_appointment_body(),
            headers=_auth(ther["token"]),
        ).status_code
        == 200
    )

    # pat2 không thấy lịch của pat1
    assert client.get("/patients/me/appointments", headers=_auth(pat2["token"])).json() == []
    # pat1 thấy đúng 1
    assert len(client.get("/patients/me/appointments", headers=_auth(pat1["token"])).json()) == 1
    # chưa đăng nhập -> 401; therapist token gọi endpoint patient -> 403
    assert client.get("/patients/me/appointments").status_code == 401
    assert (
        client.get("/patients/me/appointments", headers=_auth(ther["token"])).status_code == 403
    )
