"""
Test CÔ LẬP PHÂN QUYỀN web bác sĩ (Bước 13.1) — chống rò hồ sơ y tế.

Dựng: 2 therapist (A, B) + 3 patient:
  - patient_a : của bác sĩ A (A claim)
  - patient_b : của bác sĩ B (B claim)
  - patient_free : TỰ DO (therapist_id=NULL — trạng thái HỢP LỆ, không thuộc ai)

9 kịch bản bắt buộc (xem docstring từng test). get_owned_patient dùng
current_user.id làm khóa so sánh DƯƠNG — test 2/3 chứng minh NULL và bác sĩ khác
đều bị chặn 404.
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.enums import ResultLabel, SessionStatus
from app.models.therapy import ExerciseAssignment, ExerciseSession, SessionResult, TherapyPlan
from app.models.user import User

client = TestClient(app)


# ── Fixtures / helpers ────────────────────────────────────────────────────────

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
                    db.delete(p)  # cascade: assignments -> sessions -> results
                db.flush()
                for u in users:
                    db.delete(u)
                db.commit()
        finally:
            db.close()


def _register_patient() -> dict:
    email = f"test_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/auth/register/patient",
        json={
            "full_name": "TEST_PATIENT_DO_NOT_USE",
            "email": email,
            "password": "secret123",
            "date_of_birth": "1980-01-01",
            "gender": "male",
            "severity_level": "Nặng",
        },
    )
    assert resp.status_code == 201, resp.text
    return {"email": email, "token": resp.json()["access_token"]}


def _register_therapist() -> dict:
    email = f"test_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/auth/register/therapist",
        json={
            "full_name": "TEST_THERAPIST_DO_NOT_USE",
            "email": email,
            "password": "secret123",
            "license_no": f"LIC-{uuid.uuid4().hex[:6]}",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["role"] == "therapist"
    return {"email": email, "token": data["access_token"]}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _claim(therapist_token: str, patient_email: str, **extra) -> object:
    return client.post(
        "/therapist/patients/claim",
        json={"email": patient_email, **extra},
        headers=_auth(therapist_token),
    )


def _patient_id_of(email: str) -> str:
    db = SessionLocal()
    try:
        return str(db.query(User).filter(User.email == email).one().id)
    finally:
        db.close()


def _setup_world():
    """2 therapist A/B + 3 patient (của A, của B, tự do). Trả dict đủ token/id."""
    ther_a, ther_b = _register_therapist(), _register_therapist()
    pat_a, pat_b, pat_free = _register_patient(), _register_patient(), _register_patient()

    assert _claim(ther_a["token"], pat_a["email"]).status_code == 200
    assert _claim(ther_b["token"], pat_b["email"]).status_code == 200
    # pat_free: KHÔNG claim — therapist_id giữ NULL (hợp lệ)

    return {
        "ther_a": ther_a,
        "ther_b": ther_b,
        "pat_a_id": _patient_id_of(pat_a["email"]),
        "pat_b_id": _patient_id_of(pat_b["email"]),
        "pat_free_id": _patient_id_of(pat_free["email"]),
        "pat_a_email": pat_a["email"],
        "pat_a_token": pat_a["token"],
    }


def _add_graded_session(patient_id: str, score: float = 88.0) -> None:
    """Chèn thẳng 1 session graded + result cho patient (test bất biến #7)."""
    db = SessionLocal()
    try:
        assignment = (
            db.query(ExerciseAssignment)
            .join(TherapyPlan, ExerciseAssignment.plan_id == TherapyPlan.id)
            .filter(TherapyPlan.patient_id == uuid.UUID(patient_id))
            .first()
        )
        assert assignment is not None, "patient phải có assignment (plan tự tạo lúc đăng ký)"
        now = datetime.now(timezone.utc)
        sess = ExerciseSession(
            assignment_id=assignment.id,
            patient_id=uuid.UUID(patient_id),
            started_at=now,
            completed_at=now,
            status=SessionStatus.graded,
        )
        db.add(sess)
        db.flush()
        db.add(
            SessionResult(
                session_id=sess.id,
                attempt_number=1,
                score=score,
                result=ResultLabel.pass_,
                components={},
            )
        )
        db.commit()
    finally:
        db.close()


# ── 9 kịch bản cô lập ─────────────────────────────────────────────────────────

def test_1_a_views_own_patient_200(cleanup_test_data):
    """1. A xem chi tiết bệnh nhân của A -> 200, đúng shape dashboard."""
    w = _setup_world()
    resp = client.get(f"/therapist/patients/{w['pat_a_id']}", headers=_auth(w["ther_a"]["token"]))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["daily_scores"]) == 7
    assert len(data["daily_scores_30"]) == 30
    assert "streak" in data and "difficult_words" in data


def test_2_a_views_b_patient_404(cleanup_test_data):
    """2. A xem bệnh nhân của B -> 404 (không lộ tồn tại)."""
    w = _setup_world()
    resp = client.get(f"/therapist/patients/{w['pat_b_id']}", headers=_auth(w["ther_a"]["token"]))
    assert resp.status_code == 404


def test_3_a_views_free_patient_404(cleanup_test_data):
    """3. A xem bệnh nhân TỰ DO (therapist_id=NULL) -> 404 (NULL không lọt so sánh dương)."""
    w = _setup_world()
    resp = client.get(
        f"/therapist/patients/{w['pat_free_id']}", headers=_auth(w["ther_a"]["token"])
    )
    assert resp.status_code == 404


def test_4_patient_token_forbidden_403(cleanup_test_data):
    """4. Token PATIENT gọi endpoint bác sĩ -> 403 (cả 3 endpoint)."""
    w = _setup_world()
    h = _auth(w["pat_a_token"])
    assert client.get("/therapist/me/patients", headers=h).status_code == 403
    assert client.get(f"/therapist/patients/{w['pat_a_id']}", headers=h).status_code == 403
    assert (
        client.post(
            "/therapist/patients/claim", json={"email": w["pat_a_email"]}, headers=h
        ).status_code
        == 403
    )


def test_5_unauthenticated_401():
    """5. Chưa đăng nhập -> 401 (cả 3 endpoint)."""
    assert client.get("/therapist/me/patients").status_code == 401
    assert client.get(f"/therapist/patients/{uuid.uuid4()}").status_code == 401
    assert (
        client.post("/therapist/patients/claim", json={"email": "x@example.com"}).status_code
        == 401
    )


def test_6_list_only_own_patients(cleanup_test_data):
    """6. Danh sách của A: CHỨA bệnh nhân A, KHÔNG chứa của B, KHÔNG chứa tự do."""
    w = _setup_world()
    resp = client.get("/therapist/me/patients", headers=_auth(w["ther_a"]["token"]))
    assert resp.status_code == 200
    ids = {p["patient_id"] for p in resp.json()}
    assert w["pat_a_id"] in ids
    assert w["pat_b_id"] not in ids
    assert w["pat_free_id"] not in ids


def test_7_invariant_b_activity_does_not_change_a(cleanup_test_data):
    """7. BẤT BIẾN: thêm session graded cho bệnh nhân của B -> danh sách + chi tiết của A KHÔNG đổi."""
    w = _setup_world()
    h_a = _auth(w["ther_a"]["token"])

    before_list = client.get("/therapist/me/patients", headers=h_a).json()
    before_detail = client.get(f"/therapist/patients/{w['pat_a_id']}", headers=h_a).json()

    _add_graded_session(w["pat_b_id"], score=88.0)

    after_list = client.get("/therapist/me/patients", headers=h_a).json()
    after_detail = client.get(f"/therapist/patients/{w['pat_a_id']}", headers=h_a).json()

    assert after_list == before_list
    assert after_detail == before_detail


def test_8_claim_three_branches(cleanup_test_data):
    """8. Claim: NULL->A ("claimed"); A claim lại->200 ("updated", idempotent); B claim của A->409."""
    ther_a, ther_b = _register_therapist(), _register_therapist()
    pat = _register_patient()

    r1 = _claim(ther_a["token"], pat["email"], aphasia_type="Broca", hospital_name="BV Chợ Rẫy")
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "claimed"

    r2 = _claim(ther_a["token"], pat["email"], severity_level="Trung bình")
    assert r2.status_code == 200
    assert r2.json()["status"] == "updated"

    r3 = _claim(ther_b["token"], pat["email"])
    assert r3.status_code == 409
    assert "bác sĩ khác" in r3.json()["detail"]

    # Hồ sơ đã được ghi (aphasia_type từ r1, severity từ r2 — không đè None)
    listed = client.get("/therapist/me/patients", headers=_auth(ther_a["token"])).json()
    me = next(p for p in listed if p["email"] == pat["email"])
    assert me["aphasia_type"] == "Broca"
    assert me["hospital_name"] == "BV Chợ Rẫy"
    assert me["severity_level"] == "Trung bình"


def test_9_claim_unknown_email_404(cleanup_test_data):
    """9. Claim email không tồn tại (hoặc không phải patient) -> 404."""
    ther = _register_therapist()
    r = _claim(ther["token"], f"khongton_{uuid.uuid4().hex[:8]}@example.com")
    assert r.status_code == 404
    # Email của một THERAPIST (tồn tại nhưng không phải patient) -> cũng 404
    other = _register_therapist()
    r2 = _claim(ther["token"], other["email"])
    assert r2.status_code == 404
