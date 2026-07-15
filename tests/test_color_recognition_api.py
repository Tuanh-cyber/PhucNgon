"""
Test GĐ2 color_recognition: lấy bài (4 ô, không lộ đáp án) + chấm nhị phân + nối phiên.
Đường nộp riêng — bài nói + logic_sequence không đổi (toàn bộ test cũ vẫn xanh).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.color_recognition import ColorRecognitionExercise
from app.models.therapy import ExerciseSession, TherapyPlan
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
                for s in (
                    db.query(ExerciseSession)
                    .filter(
                        ExerciseSession.patient_id.in_(user_ids),
                        ExerciseSession.assignment_id.is_(None),  # sequence + color
                    )
                    .all()
                ):
                    db.delete(s)
                db.flush()
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


def _register_patient() -> dict:
    email = f"test_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/auth/register/patient",
        json={
            "full_name": "TEST_PATIENT_DO_NOT_USE",
            "email": email,
            "password": "secret123",
            "phone_number": f"09{int(uuid.uuid4().hex[:8], 16) % 10**8:08d}",
            "date_of_birth": "1980-01-01",
            "gender": "male",
        },
    )
    assert resp.status_code == 201, resp.text
    return {"email": email, "token": resp.json()["access_token"]}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _answer_of(exercise_code: str) -> str:
    """Màu đúng từ DB (test được phép nhìn đáp án)."""
    db = SessionLocal()
    try:
        ex = (
            db.query(ColorRecognitionExercise)
            .filter(ColorRecognitionExercise.exercise_code == exercise_code)
            .one()
        )
        return ex.target_color.color_id
    finally:
        db.close()


def test_get_content_4_options_no_leak(cleanup_test_data):
    """4 options (1 đúng + 3 nhiễu khác nhau), có hex + audio, KHÔNG đánh dấu ô đúng."""
    pat = _register_patient()
    r = client.get("/color-recognition/CLR001", headers=_auth(pat["token"]))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["exercise_type"] == "color_recognition"
    assert data["instruction_audio_url"] == "/static/color-audio/red.wav"
    assert len(data["options"]) == 4
    ids = [o["color_id"] for o in data["options"]]
    assert len(set(ids)) == 4                      # 4 màu khác nhau
    assert _answer_of("CLR001") in ids             # màu đúng nằm trong 4 ô
    for o in data["options"]:
        assert set(o.keys()) == {"color_id", "name", "hex_code"}  # KHÔNG có cờ đúng/sai
        assert o["hex_code"].startswith("#")
    # bài lạ -> 404; chưa đăng nhập -> 401
    assert client.get("/color-recognition/CLR999", headers=_auth(pat["token"])).status_code == 404
    assert client.get("/color-recognition/CLR001").status_code == 401


def test_submit_binary_and_retry(cleanup_test_data):
    """Sai -> 0/retry + correct_color_id; nộp lại đúng -> 100/correct, attempt=2."""
    pat = _register_patient()
    correct = _answer_of("CLR002")
    wrong = "COL001" if correct != "COL001" else "COL003"

    r0 = client.post(
        "/color-recognition/CLR002/submit",
        json={"selected_color_id": wrong},
        headers=_auth(pat["token"]),
    )
    assert r0.status_code == 200, r0.text
    d0 = r0.json()
    assert d0["score"] == 0 and d0["result"] == "retry" and d0["completed"] is False
    assert d0["is_correct"] is False and d0["attempt_number"] == 1
    assert d0["correct_color_id"] == correct       # đáp án lộ SAU khi nộp

    r1 = client.post(
        "/color-recognition/CLR002/submit",
        json={"selected_color_id": correct},
        headers=_auth(pat["token"]),
    )
    d1 = r1.json()
    assert d1["score"] == 100 and d1["result"] == "correct" and d1["completed"] is True
    assert d1["attempt_number"] == 2               # cùng ExerciseSession, retry tăng attempt

    # màu không tồn tại -> 422
    assert (
        client.post(
            "/color-recognition/CLR002/submit",
            json={"selected_color_id": "COL999"},
            headers=_auth(pat["token"]),
        ).status_code
        == 422
    )


def test_session_mode_color_recognition(cleanup_test_data):
    """start mode=color_recognition -> 10 bài kind đúng, không topic; nộp đúng kèm sid
    -> completed_count tăng; phiên lạ -> 404."""
    pat = _register_patient()
    start = client.post(
        "/sessions/start", json={"mode": "color_recognition"}, headers=_auth(pat["token"])
    ).json()
    assert start["mode"] == "color_recognition"
    assert start["topic"] is None and start["vocab_level"] is None
    assert len(start["exercises"]) == 10
    assert all(e["exercise_kind"] == "color_recognition" for e in start["exercises"])
    assert all(e["exercise_id"].startswith("CLR") for e in start["exercises"])

    sid = start["session_id"]
    code = start["exercises"][0]["exercise_id"]
    r = client.post(
        f"/color-recognition/{code}/submit",
        json={"selected_color_id": _answer_of(code), "therapy_session_id": sid},
        headers=_auth(pat["token"]),
    )
    assert r.status_code == 200, r.text

    st = client.get(f"/sessions/{sid}", headers=_auth(pat["token"])).json()
    assert st["completed_count"] == 1

    assert (
        client.post(
            f"/color-recognition/{code}/submit",
            json={"selected_color_id": _answer_of(code), "therapy_session_id": str(uuid.uuid4())},
            headers=_auth(pat["token"]),
        ).status_code
        == 404
    )
