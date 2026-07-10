"""
Test 3 endpoint mới cho trang chủ Frontend:
  - GET /plans/me/topics?type=...                (màn "Chọn chủ đề")
  - GET /plans/me/assignments?type=mixed&topic=  (chế độ trộn 3 dạng)
  - GET /patients/me/progress-dashboard          (dashboard tiến trình)

Pattern giống test_submit_attempt.py: đăng ký patient thật qua API (tự tạo plan),
monkeypatch ASR khi cần tạo SessionResult, cleanup xoá plan + user sau mỗi test.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.content import Exercise
from app.models.enums import ExerciseType
from app.models.therapy import ExerciseAssignment, TherapyPlan
from app.models.user import User
from app.services import asr_service
from tests.test_audio_service import _make_wav

client = TestClient(app)


# ── Cleanup fixture (giống test_submit_attempt) ───────────────────────────────
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
    data = resp.json()
    data["email"] = email
    return data


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _assignment_of_type(email: str, exercise_type: ExerciseType):
    """(assignment_id, canonical_word) của 1 bài thuộc dạng cho trước trong plan."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assignment = (
            db.query(ExerciseAssignment)
            .join(TherapyPlan, ExerciseAssignment.plan_id == TherapyPlan.id)
            .join(Exercise, ExerciseAssignment.exercise_id == Exercise.id)
            .filter(
                TherapyPlan.patient_id == user.id,
                Exercise.exercise_type == exercise_type,
            )
            .first()
        )
        assert assignment is not None
        return assignment.id, assignment.exercise.target_vocab.canonical_word
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# 1. GET /plans/me/topics
# ══════════════════════════════════════════════════════════════════════════════

def test_topics_returns_only_topics_with_exercises(cleanup_test_data):
    token = _register_patient()["access_token"]

    resp = client.get("/plans/me/topics", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    topics = resp.json()

    assert len(topics) > 0
    # Đối chiếu với DB: tập topic trả về = ĐÚNG tập topic có bài trong plan
    resp_all = client.get("/plans/me/assignments?type=mixed", headers=_auth(token))
    assert resp_all.status_code == 200
    expected_topics = {a["topic"] for a in resp_all.json()}
    assert {t["topic"] for t in topics} == expected_topics

    for t in topics:
        assert t["topic_display"]          # có tên tiếng Việt
        assert t["total_count"] > 0        # chỉ trả topic THẬT SỰ có bài
        assert t["completed_count"] == 0   # vừa đăng ký, chưa làm bài


def test_topics_filtered_by_type(cleanup_test_data):
    token = _register_patient()["access_token"]

    resp = client.get("/plans/me/topics?type=naming", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    naming_total = sum(t["total_count"] for t in resp.json())

    # Tổng số bài naming qua topics == tổng qua assignments (cùng bộ lọc)
    resp_list = client.get("/plans/me/assignments?type=naming", headers=_auth(token))
    assert naming_total == len(resp_list.json())


def test_topics_invalid_type_422(cleanup_test_data):
    token = _register_patient()["access_token"]
    resp = client.get("/plans/me/topics?type=khong_ton_tai", headers=_auth(token))
    assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# 2. GET /plans/me/assignments?type=mixed&topic=...
# ══════════════════════════════════════════════════════════════════════════════

def test_assignments_mixed_by_topic(cleanup_test_data):
    token = _register_patient()["access_token"]

    # Chọn 1 topic có bài >=2 dạng (nếu plan không có topic nào đủ 2 dạng thì
    # ít nhất vẫn kiểm tra được: chỉ chứa đúng topic đã lọc).
    topics = client.get("/plans/me/topics", headers=_auth(token)).json()
    assert topics
    topic = max(topics, key=lambda t: t["total_count"])["topic"]

    resp = client.get(
        f"/plans/me/assignments?type=mixed&topic={topic}", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert items
    assert all(a["topic"] == topic for a in items)           # đúng topic đã lọc
    types_in_list = {a["exercise_type"] for a in items}
    assert types_in_list <= {
        "naming", "command_identification", "sentence_building"
    }

    # Trộn ổn định TRONG NGÀY: gọi lần 2 phải ra đúng thứ tự y hệt
    resp2 = client.get(
        f"/plans/me/assignments?type=mixed&topic={topic}", headers=_auth(token)
    )
    assert [a["assignment_id"] for a in resp2.json()] == [
        a["assignment_id"] for a in items
    ]


def test_assignments_mixed_returns_all_three_types(cleanup_test_data):
    # Không lọc topic: mixed phải gom bài của CẢ 3 dạng trong plan (plan tự tạo
    # lúc đăng ký có đủ 3 dạng).
    token = _register_patient()["access_token"]
    resp = client.get("/plans/me/assignments?type=mixed", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    types_in_list = {a["exercise_type"] for a in resp.json()}
    assert types_in_list == {"naming", "command_identification", "sentence_building"}


def test_assignments_single_type_with_topic_sorted(cleanup_test_data):
    token = _register_patient()["access_token"]
    topics = client.get(
        "/plans/me/topics?type=naming", headers=_auth(token)
    ).json()
    assert topics
    topic = topics[0]["topic"]

    resp = client.get(
        f"/plans/me/assignments?type=naming&topic={topic}", headers=_auth(token)
    )
    items = resp.json()
    assert items
    assert all(a["exercise_type"] == "naming" and a["topic"] == topic for a in items)
    order = [a["order_index"] for a in items]
    assert order == sorted(order)      # dạng đơn: sắp theo order_index


def test_assignments_invalid_topic_422(cleanup_test_data):
    token = _register_patient()["access_token"]
    resp = client.get(
        "/plans/me/assignments?type=naming&topic=khong_ton_tai", headers=_auth(token)
    )
    assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# 3. GET /patients/me/progress-dashboard
# ══════════════════════════════════════════════════════════════════════════════

def test_dashboard_empty_for_new_patient(cleanup_test_data):
    token = _register_patient()["access_token"]

    resp = client.get("/patients/me/progress-dashboard", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # 7 ngày, toàn null (chưa làm bài nào)
    assert len(data["daily_scores"]) == 7
    assert all(d["avg_score"] is None and d["session_count"] == 0
               for d in data["daily_scores"])
    assert data["streak"]["current_streak_days"] == 0
    assert data["streak"]["active_days_last_30"] == []
    assert data["difficult_words"] == []


def test_dashboard_after_attempts(cleanup_test_data, monkeypatch):
    """1 bài pass + 1 bài fail -> hôm nay có điểm, streak >=1, từ fail vào difficult_words."""
    reg = _register_patient()
    token = reg["access_token"]

    # Bài 1: nói ĐÚNG -> pass (graded -> tính streak)
    a1, word1 = _assignment_of_type(reg["email"], ExerciseType.naming)
    monkeypatch.setattr(
        asr_service, "transcribe_audio",
        lambda wav: {"transcript": word1, "confidence": 0.9},
    )
    wav = _make_wav(duration_s=2.0, amplitude=8000)
    r1 = client.post(
        f"/assignments/{a1}/submit",
        files={"audio_file": ("t.wav", wav, "audio/wav")},
        headers=_auth(token),
    )
    assert r1.status_code == 200 and r1.json()["result"] == "pass", r1.text

    # Bài 2: nói SAI HẲN -> retry (fail -> vào difficult_words)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == reg["email"]).first()
        a2_row = (
            db.query(ExerciseAssignment)
            .join(TherapyPlan, ExerciseAssignment.plan_id == TherapyPlan.id)
            .join(Exercise, ExerciseAssignment.exercise_id == Exercise.id)
            .filter(
                TherapyPlan.patient_id == user.id,
                Exercise.exercise_type == ExerciseType.naming,
                ExerciseAssignment.id != a1,
            )
            .first()
        )
        a2, word2 = a2_row.id, a2_row.exercise.target_vocab.canonical_word
    finally:
        db.close()

    monkeypatch.setattr(
        asr_service, "transcribe_audio",
        lambda wav: {"transcript": "hoàn toàn sai bét", "confidence": 0.9},
    )
    r2 = client.post(
        f"/assignments/{a2}/submit",
        files={"audio_file": ("t.wav", _make_wav(duration_s=2.0, amplitude=8000), "audio/wav")},
        headers=_auth(token),
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["result"] in ("retry", "near")

    resp = client.get("/patients/me/progress-dashboard", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()

    today_entry = data["daily_scores"][-1]           # phần tử cuối = hôm nay
    assert today_entry["session_count"] >= 2
    assert today_entry["avg_score"] is not None

    assert data["streak"]["current_streak_days"] >= 1     # bài 1 pass -> graded hôm nay
    assert today_entry["date"] in data["streak"]["active_days_last_30"]

    words = {w["word"] for w in data["difficult_words"]}
    assert word2 in words                            # từ nói sai phải xuất hiện
    assert word1 not in words                        # từ pass ngay lần 1 thì không
    for w in data["difficult_words"]:
        assert w["fail_count"] >= 1
        assert w["attempts"] >= w["fail_count"]


def test_dashboard_requires_patient_role(cleanup_test_data):
    resp = client.get("/patients/me/progress-dashboard")
    assert resp.status_code in (401, 403)
