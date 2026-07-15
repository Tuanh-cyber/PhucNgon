"""
Test GĐ2 logic_sequence: lấy bài (xáo, không lộ đáp án) + nộp/chấm nhị phân + nối phiên.

Đường nộp TÁCH RIÊNG khỏi submit bài nói — bài nói không đổi (bảo đảm bởi toàn bộ
test cũ vẫn xanh).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.sequence import LogicSequenceExercise, Sequence, SequenceStep
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
                # ExerciseSession của logic_sequence KHÔNG cascade theo plan (assignment
                # NULL) -> xóa tay trước; rồi plans, therapy_sessions, users.
                for s in (
                    db.query(ExerciseSession)
                    .filter(
                        ExerciseSession.patient_id.in_(user_ids),
                        ExerciseSession.logic_sequence_exercise_id.isnot(None),
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


def _correct_order_of(exercise_id: str) -> list[str]:
    """Thứ tự ĐÚNG từ DB (test được phép nhìn đáp án)."""
    db = SessionLocal()
    try:
        ex = db.query(LogicSequenceExercise).filter(
            LogicSequenceExercise.id == uuid.UUID(exercise_id)
        ).one()
        steps = (
            db.query(SequenceStep)
            .filter(SequenceStep.sequence_id == ex.target_sequence_id)
            .order_by(SequenceStep.step_order)
            .all()
        )
        return [str(s.id) for s in steps]
    finally:
        db.close()


def _any_exercise_id() -> str:
    db = SessionLocal()
    try:
        return str(db.query(LogicSequenceExercise).first().id)
    finally:
        db.close()


def test_get_content_shuffled_no_answer_leak(cleanup_test_data):
    """Lấy bài: đủ số bước + audio, mỗi bước có step_id/image_url, KHÔNG lộ step_order."""
    pat = _register_patient()
    ex_id = _any_exercise_id()
    r = client.get(f"/logic-sequence/{ex_id}", headers=_auth(pat["token"]))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["exercise_type"] == "logic_sequence"
    assert data["step_count"] == len(data["steps"])
    assert data["level"] in (1, 2, 3)
    assert data["instruction_audio_url"] == "/static/sequence/instruction_audio.wav"
    for s in data["steps"]:
        assert set(s.keys()) == {"step_id", "image_url"}  # KHÔNG có step_order
        assert s["image_url"] and s["image_url"].startswith("/static/sequence/level")
    # step_id đúng tập các bước của bài (không thiếu/thừa)
    assert sorted(s["step_id"] for s in data["steps"]) == sorted(_correct_order_of(ex_id))
    # bài không tồn tại -> 404; chưa đăng nhập -> 401
    assert client.get(f"/logic-sequence/{uuid.uuid4()}", headers=_auth(pat["token"])).status_code == 404
    assert client.get(f"/logic-sequence/{ex_id}").status_code == 401


def test_submit_correct_100_wrong_0_with_feedback(cleanup_test_data):
    """Nộp đúng -> 100/correct/completed; sai -> 0/retry + step_feedback đánh dấu đúng chỗ."""
    pat = _register_patient()
    ex_id = _any_exercise_id()
    correct = _correct_order_of(ex_id)

    # SAI: đảo 2 bước đầu -> score 0, retry; feedback: 2 vị trí đầu sai, còn lại đúng
    wrong = [correct[1], correct[0]] + correct[2:]
    r0 = client.post(
        f"/logic-sequence/{ex_id}/submit",
        json={"ordered_step_ids": wrong},
        headers=_auth(pat["token"]),
    )
    assert r0.status_code == 200, r0.text
    d0 = r0.json()
    assert d0["score"] == 0 and d0["result"] == "retry" and d0["completed"] is False
    assert d0["attempt_number"] == 1
    fb = {f["step_id"]: f for f in d0["step_feedback"]}
    assert fb[correct[1]]["position"] == 1 and fb[correct[1]]["correct"] is False
    assert fb[correct[0]]["position"] == 2 and fb[correct[0]]["correct"] is False
    for sid in correct[2:]:
        assert fb[sid]["correct"] is True
    assert d0["correct_order"] == correct  # đáp án CHỈ lộ sau khi nộp

    # ĐÚNG: retry lần 2 -> 100, correct, attempt_number=2
    r1 = client.post(
        f"/logic-sequence/{ex_id}/submit",
        json={"ordered_step_ids": correct},
        headers=_auth(pat["token"]),
    )
    d1 = r1.json()
    assert d1["score"] == 100 and d1["result"] == "correct" and d1["completed"] is True
    assert d1["attempt_number"] == 2
    assert all(f["correct"] for f in d1["step_feedback"])

    # Thiếu/thừa/lạ step -> 422
    assert (
        client.post(
            f"/logic-sequence/{ex_id}/submit",
            json={"ordered_step_ids": correct[:-1]},
            headers=_auth(pat["token"]),
        ).status_code
        == 422
    )


def test_submit_with_session_counts_progress(cleanup_test_data):
    """Phiên mode=logic_sequence: 10 bài kind=logic_sequence; nộp đúng kèm sid ->
    completed_count tăng (x/10 đếm từ backend)."""
    pat = _register_patient()
    start = client.post(
        "/sessions/start", json={"mode": "logic_sequence"}, headers=_auth(pat["token"])
    ).json()
    assert start["mode"] == "logic_sequence"
    assert start["topic"] is None and start["vocab_level"] is None
    assert len(start["exercises"]) == 10
    assert all(e["exercise_kind"] == "logic_sequence" for e in start["exercises"])
    assert all(e["exercise_type"] == "logic_sequence" for e in start["exercises"])

    sid = start["session_id"]
    ex_id = start["exercises"][0]["exercise_id"]
    r = client.post(
        f"/logic-sequence/{ex_id}/submit",
        json={"ordered_step_ids": _correct_order_of(ex_id), "therapy_session_id": sid},
        headers=_auth(pat["token"]),
    )
    assert r.status_code == 200, r.text

    st = client.get(f"/sessions/{sid}", headers=_auth(pat["token"])).json()
    assert st["completed_count"] == 1

    fin = client.post(f"/sessions/{sid}/finish", headers=_auth(pat["token"])).json()
    assert fin["status"] == "stopped_early" and fin["completed_count"] == 1

    # Phiên không tồn tại -> 404 (validate trước khi ghi)
    assert (
        client.post(
            f"/logic-sequence/{ex_id}/submit",
            json={
                "ordered_step_ids": _correct_order_of(ex_id),
                "therapy_session_id": str(uuid.uuid4()),
            },
            headers=_auth(pat["token"]),
        ).status_code
        == 404
    )
