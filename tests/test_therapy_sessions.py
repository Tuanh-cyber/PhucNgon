"""
Test PHIÊN TẬP (rule.md mục 3): start -> 10 bài -> submit gắn phiên -> finish.
Luồng cũ (submit KHÔNG kèm therapy_session_id) phải chạy y nguyên — bảo đảm bởi
toàn bộ test cũ vẫn xanh (không file test cũ nào gửi therapy_session_id).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.therapy import TherapyPlan
from app.models.therapy_session import TherapySession
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
                # Plans (cascade: assignments -> exercise_sessions -> results) trước;
                # therapy_sessions bị exercise_sessions FK trỏ tới -> xóa SAU plans.
                for p in (
                    db.query(TherapyPlan).filter(TherapyPlan.patient_id.in_(user_ids)).all()
                ):
                    db.delete(p)
                db.flush()
                db.query(TherapySession).filter(
                    TherapySession.patient_id.in_(user_ids)
                ).delete(synchronize_session=False)
                for u in users:
                    db.delete(u)
                db.commit()
        finally:
            db.close()


def _register_patient(aphasia: str | None = None) -> dict:
    email = f"test_{uuid.uuid4().hex[:10]}@example.com"
    body = {
        "full_name": "TEST_PATIENT_DO_NOT_USE",
        "email": email,
        "password": "secret123",
        "phone_number": f"09{int(uuid.uuid4().hex[:8], 16) % 10**8:08d}",
        "date_of_birth": "1980-01-01",
        "gender": "male",
        "severity_level": "Nặng",
    }
    if aphasia:
        body["aphasia_type"] = aphasia
    resp = client.post("/auth/register/patient", json=body)
    assert resp.status_code == 201, resp.text
    return {"email": email, "token": resp.json()["access_token"]}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _submit_recognition(token: str, assignment_id: str, therapy_session_id: str) -> None:
    """Nộp 1 bài CMD recognition (không cần ASR): chọn 1 lựa chọn bất kỳ -> graded ngay."""
    content = client.get(f"/assignments/{assignment_id}/content", headers=_auth(token)).json()
    assert content["mode"] == "recognition"
    choice = content["choices"][0]["vocab_id"]
    r = client.post(
        f"/assignments/{assignment_id}/submit",
        data={"selected_vocab_id": choice, "therapy_session_id": therapy_session_id},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_final"] is True  # recognition: correct/incorrect đều final


def _recognition_assignments(token: str, exercises: list[dict]) -> list[dict]:
    """Lọc các bài CMD mode=recognition trong danh sách phiên (submit không cần audio)."""
    out = []
    for it in exercises:
        if it["exercise_type"] != "command_identification":
            continue
        c = client.get(f"/assignments/{it['assignment_id']}/content", headers=_auth(token)).json()
        if c.get("mode") == "recognition":
            out.append(it)
    return out


def test_start_session_returns_10_exercises(cleanup_test_data):
    """start (mixed + Mixed Topics) -> đúng 10 bài, profile snapshot đúng, vocab_level=None."""
    pat = _register_patient(aphasia="Aphasia Broca")
    r = client.post("/sessions/start", json={"mode": "mixed"}, headers=_auth(pat["token"]))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["planned_count"] == 10
    assert len(data["exercises"]) == 10
    assert data["profile"] == "broca_like"          # snapshot từ aphasia_type
    assert data["topic"] is None                    # Mixed Topics
    assert data["vocab_level"] is None              # level theo từng bài
    assert all(e["status"] == "pending" for e in data["exercises"])

    # GET trạng thái: 0/10, in_progress
    st = client.get(f"/sessions/{data['session_id']}", headers=_auth(pat["token"])).json()
    assert st["status"] == "in_progress"
    assert st["completed_count"] == 0
    assert st["total_retry_count"] == 0


def test_session_submit_finish_stopped_early(cleanup_test_data):
    """Submit vài bài GẮN PHIÊN -> completed_count tăng; finish khi chưa đủ 10 ->
    stopped_early + duration_seconds được tính."""
    pat = _register_patient()
    # Mode CMD với đủ 10 bài; topic để trống (Mixed Topics) cho chắc đủ bài recognition
    start = client.post(
        "/sessions/start",
        json={"mode": "command_identification"},
        headers=_auth(pat["token"]),
    ).json()
    sid = start["session_id"]
    assert start["vocab_level"] is None  # Mixed Topics

    recogs = _recognition_assignments(pat["token"], start["exercises"])
    assert len(recogs) >= 2, "plan cần >=2 bài recognition để test"
    for it in recogs[:2]:
        _submit_recognition(pat["token"], it["assignment_id"], sid)

    st = client.get(f"/sessions/{sid}", headers=_auth(pat["token"])).json()
    assert st["completed_count"] == 2

    fin = client.post(f"/sessions/{sid}/finish", headers=_auth(pat["token"]))
    assert fin.status_code == 200, fin.text
    fdata = fin.json()
    assert fdata["status"] == "stopped_early"       # 2/10 -> dừng sớm
    assert fdata["completed_count"] == 2
    assert fdata["ended_at"] is not None
    assert fdata["duration_seconds"] is not None and fdata["duration_seconds"] >= 0

    # Finish lần 2 -> 409 (phiên đã kết thúc)
    assert client.post(f"/sessions/{sid}/finish", headers=_auth(pat["token"])).status_code == 409


def test_session_with_topic_has_vocab_level(cleanup_test_data):
    """start với topic cụ thể -> vocab_level = level TopicProgress (mặc định 1)."""
    pat = _register_patient()
    # Tìm 1 topic có bài naming trong plan
    topics = client.get("/plans/me/topics?type=naming", headers=_auth(pat["token"])).json()
    assert topics, "plan phải có topic naming"
    topic = topics[0]["topic"]

    r = client.post(
        "/sessions/start", json={"mode": "naming", "topic": topic}, headers=_auth(pat["token"])
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["vocab_level"] == 1                 # chưa có TopicProgress -> level 1
    assert all(e["topic"] == topic for e in data["exercises"])
    assert all(e["exercise_type"] == "naming" for e in data["exercises"])


def test_session_isolation_and_validation(cleanup_test_data):
    """Phiên của người khác -> 404; topic rác -> 422; submit kèm phiên không tồn tại -> 404;
    submit kèm phiên ĐÃ KẾT THÚC -> 404."""
    p1, p2 = _register_patient(), _register_patient()
    sid = client.post("/sessions/start", json={"mode": "mixed"}, headers=_auth(p1["token"])).json()[
        "session_id"
    ]

    # p2 không đọc/finish được phiên của p1
    assert client.get(f"/sessions/{sid}", headers=_auth(p2["token"])).status_code == 404
    assert client.post(f"/sessions/{sid}/finish", headers=_auth(p2["token"])).status_code == 404

    # topic rác -> 422
    assert (
        client.post(
            "/sessions/start", json={"mode": "naming", "topic": "khong_co"}, headers=_auth(p1["token"])
        ).status_code
        == 422
    )

    # Submit kèm phiên KHÔNG tồn tại -> 404 (validate trước khi chấm)
    ex = client.post("/sessions/start", json={"mode": "command_identification"}, headers=_auth(p1["token"])).json()
    recogs = _recognition_assignments(p1["token"], ex["exercises"])
    assert recogs
    content = client.get(
        f"/assignments/{recogs[0]['assignment_id']}/content", headers=_auth(p1["token"])
    ).json()
    r = client.post(
        f"/assignments/{recogs[0]['assignment_id']}/submit",
        data={
            "selected_vocab_id": content["choices"][0]["vocab_id"],
            "therapy_session_id": str(uuid.uuid4()),
        },
        headers=_auth(p1["token"]),
    )
    assert r.status_code == 404

    # Phiên đã finish -> submit kèm nó cũng 404 ("phiên đang mở" mới nhận)
    client.post(f"/sessions/{sid}/finish", headers=_auth(p1["token"]))
    r2 = client.post(
        f"/assignments/{recogs[0]['assignment_id']}/submit",
        data={
            "selected_vocab_id": content["choices"][0]["vocab_id"],
            "therapy_session_id": sid,
        },
        headers=_auth(p1["token"]),
    )
    assert r2.status_code == 404
