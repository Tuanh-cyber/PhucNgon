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


def _unique_phone() -> str:
    """Sđt VN 10 số duy nhất cho mỗi lần gọi (09 + 8 chữ số từ uuid)."""
    return f"09{int(uuid.uuid4().hex[:8], 16) % 10**8:08d}"


def _register_patient(phone: str | None = None) -> dict:
    email = f"test_{uuid.uuid4().hex[:10]}@example.com"
    phone = phone or _unique_phone()
    resp = client.post(
        "/auth/register/patient",
        json={
            "full_name": "TEST_PATIENT_DO_NOT_USE",
            "email": email,
            "password": "secret123",
            "phone_number": phone,  # claim khớp theo SĐT (Mô hình A)
            "date_of_birth": "1980-01-01",
            "gender": "male",
            "severity_level": "Nặng",
        },
    )
    assert resp.status_code == 201, resp.text
    return {"email": email, "phone": phone, "token": resp.json()["access_token"]}


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


def _claim(therapist_token: str, patient_phone: str, **extra) -> object:
    return client.post(
        "/therapist/patients/claim",
        json={"phone": patient_phone, **extra},
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

    assert _claim(ther_a["token"], pat_a["phone"]).status_code == 200
    assert _claim(ther_b["token"], pat_b["phone"]).status_code == 200
    # pat_free: KHÔNG claim — therapist_id giữ NULL (hợp lệ)

    return {
        "ther_a": ther_a,
        "ther_b": ther_b,
        "pat_a_id": _patient_id_of(pat_a["email"]),
        "pat_b_id": _patient_id_of(pat_b["email"]),
        "pat_free_id": _patient_id_of(pat_free["email"]),
        "pat_a_email": pat_a["email"],
        "pat_a_phone": pat_a["phone"],
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
    """1. A xem chi tiết bệnh nhân của A -> 200, đúng shape 13.4 (header + dashboard + insight)."""
    w = _setup_world()
    resp = client.get(f"/therapist/patients/{w['pat_a_id']}", headers=_auth(w["ther_a"]["token"]))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Khối hồ sơ
    assert data["patient"]["full_name"] == "TEST_PATIENT_DO_NOT_USE"
    assert data["patient"]["age"] >= 40  # sinh 1980
    assert data["patient"]["doctor_name"] == "TEST_THERAPIST_DO_NOT_USE"
    # Dashboard tái dùng nguyên shape app bệnh nhân
    assert len(data["dashboard"]["daily_scores"]) == 7
    assert len(data["dashboard"]["daily_scores_30"]) == 30
    assert "streak" in data["dashboard"] and "difficult_words" in data["dashboard"]
    # Metric bổ sung 13.4
    assert data["sessions_per_week"] == 0  # chưa luyện buổi nào
    assert data["insight"]["type"] in ("ok", "warn")


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
            "/therapist/patients/claim", json={"phone": w["pat_a_phone"]}, headers=h
        ).status_code
        == 403
    )


def test_5_unauthenticated_401():
    """5. Chưa đăng nhập -> 401 (cả 3 endpoint)."""
    assert client.get("/therapist/me/patients").status_code == 401
    assert client.get(f"/therapist/patients/{uuid.uuid4()}").status_code == 401
    assert (
        client.post("/therapist/patients/claim", json={"phone": "0912345678"}).status_code
        == 401
    )


def test_6_list_only_own_patients(cleanup_test_data):
    """6. Danh sách của A: CHỨA bệnh nhân A, KHÔNG chứa của B, KHÔNG chứa tự do."""
    w = _setup_world()
    resp = client.get("/therapist/me/patients", headers=_auth(w["ther_a"]["token"]))
    assert resp.status_code == 200
    data = resp.json()
    ids = {p["patient_id"] for p in data["items"]}
    assert w["pat_a_id"] in ids
    assert w["pat_b_id"] not in ids
    assert w["pat_free_id"] not in ids
    assert data["total"] == len(data["items"])


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

    r1 = _claim(ther_a["token"], pat["phone"], aphasia_type="Broca", hospital_name="BV Chợ Rẫy")
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "claimed"

    r2 = _claim(ther_a["token"], pat["phone"], severity_level="Trung bình")
    assert r2.status_code == 200
    assert r2.json()["status"] == "updated"

    r3 = _claim(ther_b["token"], pat["phone"])
    assert r3.status_code == 409
    assert "bác sĩ khác" in r3.json()["detail"]

    # Hồ sơ đã được ghi (aphasia_type từ r1, severity từ r2 — không đè None)
    listed = client.get("/therapist/me/patients", headers=_auth(ther_a["token"])).json()
    me = next(p for p in listed["items"] if p["email"] == pat["email"])
    assert me["aphasia_type"] == "Broca"
    assert me["hospital_name"] == "BV Chợ Rẫy"
    assert me["severity_level"] == "Trung bình"


def test_9_claim_unknown_phone_404(cleanup_test_data):
    """9. Claim số hợp lệ nhưng KHÔNG có bệnh nhân nào dùng -> 404 (kèm hướng dẫn đăng ký)."""
    ther = _register_therapist()
    r = _claim(ther["token"], _unique_phone())  # số hợp lệ, chưa ai đăng ký
    assert r.status_code == 404
    assert "đăng ký kèm SĐT" in r.json()["detail"]
    # Số của một THERAPIST (tồn tại trong users nhưng không phải patient) -> cũng 404
    ther_phone = _unique_phone()
    email = f"test_{uuid.uuid4().hex[:10]}@example.com"
    client.post(
        "/auth/register/therapist",
        json={
            "full_name": "TEST_THERAPIST_DO_NOT_USE",
            "email": email,
            "password": "secret123",
            "phone_number": ther_phone,
            "license_no": f"LIC-{uuid.uuid4().hex[:6]}",
        },
    )
    r2 = _claim(ther["token"], ther_phone)
    assert r2.status_code == 404


# ── 13.2/13.3/13.4: số liệu + ngưỡng ─────────────────────────────────────────

def test_10_attention_threshold_and_summary(cleanup_test_data):
    """Ngưỡng 3 ngày: bệnh nhân KHÔNG luyện -> status 'attention' + vào need_attention/banner.
    Bệnh nhân CÓ buổi graded hôm nay -> 'good' + đếm vào practicing."""
    ther = _register_therapist()
    pat_idle, pat_active = _register_patient(), _register_patient()
    assert _claim(ther["token"], pat_idle["phone"]).status_code == 200
    assert _claim(ther["token"], pat_active["phone"]).status_code == 200

    active_id = _patient_id_of(pat_active["email"])
    idle_id = _patient_id_of(pat_idle["email"])
    _add_graded_session(active_id, score=75.0)  # hôm nay -> trong cửa sổ 3 và 7 ngày

    h = _auth(ther["token"])

    # 13.2: status từng dòng
    items = client.get("/therapist/me/patients", headers=h).json()["items"]
    by_id = {p["patient_id"]: p for p in items}
    assert by_id[idle_id]["status"] == "attention"
    assert by_id[active_id]["status"] == "good"
    assert by_id[active_id]["sessions_per_week"] == 1
    assert by_id[active_id]["avg_score_2days"] == 75.0
    assert by_id[idle_id]["avg_score_2days"] is None

    # 13.2: filter status hoạt động + total sau filter
    only_attention = client.get(
        "/therapist/me/patients?status=attention", headers=h
    ).json()
    assert {p["patient_id"] for p in only_attention["items"]} == {idle_id}
    assert only_attention["total"] == 1

    # 13.3: summary đếm đúng trên tập của tôi
    s = client.get("/therapist/dashboard-summary", headers=h).json()
    assert s["total_patients"] == 2
    assert s["practicing"] == 1
    assert s["need_attention"] == 1
    assert [a["patient_id"] for a in s["attention_list"]] == [idle_id]


def test_11_summary_isolated_from_other_therapist(cleanup_test_data):
    """13.3 vẫn sau mask: bệnh nhân của B và bệnh nhân tự do KHÔNG lọt vào summary của A."""
    w = _setup_world()  # A có 1 bệnh nhân; B có 1; 1 tự do
    s = client.get("/therapist/dashboard-summary", headers=_auth(w["ther_a"]["token"])).json()
    assert s["total_patients"] == 1  # chỉ bệnh nhân của A
    ids_in_banner = {a["patient_id"] for a in s["attention_list"]}
    assert w["pat_b_id"] not in ids_in_banner
    assert w["pat_free_id"] not in ids_in_banner
    # patient token -> 403
    assert (
        client.get("/therapist/dashboard-summary", headers=_auth(w["pat_a_token"])).status_code
        == 403
    )


def test_12_detail_insight_and_delta(cleanup_test_data):
    """13.4: bệnh nhân có buổi graded điểm cao hôm nay -> sessions_per_week=1, avg_score_day
    có giá trị; insight trả type/text hợp lệ; delta None khi tuần trước trống."""
    ther = _register_therapist()
    pat = _register_patient()
    assert _claim(ther["token"], pat["phone"]).status_code == 200
    pid = _patient_id_of(pat["email"])
    _add_graded_session(pid, score=90.0)

    data = client.get(f"/therapist/patients/{pid}", headers=_auth(ther["token"])).json()
    assert data["sessions_per_week"] == 1
    assert data["avg_score_day"] == 90.0
    # Tuần trước không có dữ liệu -> delta None
    assert data["score_delta_vs_last_week"] is None
    assert data["insight"]["type"] in ("ok", "warn")
    assert len(data["insight"]["text"]) > 10


# ── Claim theo SĐT: chuẩn hóa định dạng + trùng số ───────────────────────────

def test_13_claim_phone_formats(cleanup_test_data):
    """Cùng 1 số nhập ở nhiều định dạng (+84 / có chấm / có khoảng trắng) đều khớp đúng
    1 bệnh nhân (lần đầu claimed, các lần sau updated — idempotent)."""
    ther = _register_therapist()
    base = _unique_phone()                      # vd "0912345678"
    _register_patient(phone=base)

    intl = "+84 " + base[1:3] + " " + base[3:6] + " " + base[6:]   # "+84 91 234 5678"
    dotted = base[:4] + "." + base[4:7] + "." + base[7:]            # "0912.345.678"

    r1 = _claim(ther["token"], intl)
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "claimed"

    r2 = _claim(ther["token"], dotted)
    assert r2.status_code == 200
    assert r2.json()["status"] == "updated"

    r3 = _claim(ther["token"], base)
    assert r3.status_code == 200
    assert r3.json()["status"] == "updated"


def test_14_claim_duplicate_phone_409(cleanup_test_data):
    """Hai bệnh nhân trùng số (sau chuẩn hóa) -> claim 409 'Nhiều bệnh nhân trùng số'.

    Đăng ký giờ đã CHẶN trùng số (409) nên không tạo được trùng qua API — sửa thẳng DB
    (mô phỏng dữ liệu cũ trước khi có guard) để test lớp phòng thủ thứ 2 ở claim.
    """
    ther = _register_therapist()
    dup = _unique_phone()
    _register_patient(phone=dup)
    pat2 = _register_patient()  # số khác -> đăng ký OK

    # Sửa DB: patient 2 mang biến thể "+84..." của cùng số (khác chuỗi thô, TRÙNG chuẩn hóa)
    db = SessionLocal()
    try:
        u2 = db.query(User).filter(User.email == pat2["email"]).one()
        u2.phone_number = "+84" + dup[1:]
        db.commit()
    finally:
        db.close()

    r = _claim(ther["token"], dup)
    assert r.status_code == 409
    assert "trùng số" in r.json()["detail"]


def test_15_claim_invalid_phone_422(cleanup_test_data):
    """Số không hợp lệ (chữ, quá ngắn) -> 422."""
    ther = _register_therapist()
    assert _claim(ther["token"], "abc").status_code == 422
    assert _claim(ther["token"], "123").status_code == 422
