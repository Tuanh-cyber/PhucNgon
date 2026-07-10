"""
Test 3 endpoint mới cho luồng làm bài đa loại:
  - GET /plans/me/assignments?type=...      (danh sách bài thật theo loại)
  - GET /assignments/{id}/content           (nội dung render UI — KHÔNG lộ đáp án)
  - POST /assignments/{id}/submit           (nhánh recognition: selected_vocab_id, không audio)

Dùng chung chiến lược cleanup với test_auth_router: đăng ký patient thật (email test_%),
xoá plan + user sau test (FK cascade lo phần còn lại).
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.content import Exercise
from app.models.therapy import ExerciseAssignment, TherapyPlan
from app.models.user import User

client = TestClient(app)


def _unique_email() -> str:
    return f"test_{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture
def cleanup_test_users():
    """Xoá user test (email test_%@example.com) + plan của họ sau mỗi test."""
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


def _register_patient() -> str:
    """Đăng ký 1 patient mới, trả access token."""
    resp = client.post(
        "/auth/register/patient",
        json={
            "full_name": "TEST_PATIENT_DO_NOT_USE",
            "email": _unique_email(),
            "password": "secret123",
            "date_of_birth": "1980-01-01",
            "gender": "male",
            "severity_level": "Trung bình",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _list_assignments(token: str, exercise_type: str) -> list[dict]:
    resp = client.get(
        f"/plans/me/assignments?type={exercise_type}", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── GET /plans/me/assignments ────────────────────────────────────────────────

def test_list_assignments_naming(cleanup_test_users):
    token = _register_patient()
    items = _list_assignments(token, "naming")
    assert len(items) == 10  # EXERCISES_PER_TYPE
    assert all(i["exercise_type"] == "naming" for i in items)
    assert all(i["status"] == "pending" for i in items)  # chưa làm bài nào
    # Sắp theo order_index tăng dần
    orders = [i["order_index"] for i in items]
    assert orders == sorted(orders)
    # Đủ field cho frontend
    assert {"assignment_id", "exercise_id", "exercise_type", "order_index", "status"} <= set(
        items[0].keys()
    )


def test_list_assignments_invalid_type_422(cleanup_test_users):
    token = _register_patient()
    resp = client.get("/plans/me/assignments?type=khong_ton_tai", headers=_auth(token))
    assert resp.status_code == 422


def test_list_assignments_requires_auth():
    resp = client.get("/plans/me/assignments?type=naming")
    assert resp.status_code == 401


# ── GET /assignments/{id}/content ────────────────────────────────────────────

def test_naming_content_has_image_and_no_answer_leak(cleanup_test_users):
    token = _register_patient()
    items = _list_assignments(token, "naming")

    resp = client.get(
        f"/assignments/{items[0]['assignment_id']}/content", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["exercise_type"] == "naming"
    # Câu hỏi naming đổi theo chủ đề của bài -> phải là 1 trong các prompt hợp lệ
    # (6 chủ đề đã map + default), không còn cố định 1 chuỗi.
    from app.routers.attempts import NAMING_PROMPT_BY_TOPIC, NAMING_PROMPT_DEFAULT

    valid_prompts = set(NAMING_PROMPT_BY_TOPIC.values()) | {NAMING_PROMPT_DEFAULT}
    assert data["prompt"] in valid_prompts
    # vocab_audio_url: hoặc null (file thiếu) hoặc /static/vocab-audio/... (đã backfill)
    if data["vocab_audio_url"] is not None:
        assert data["vocab_audio_url"].startswith("/static/vocab-audio/")
    # image_url: hoặc null (file thiếu) hoặc đường dẫn static đúng prefix
    if data["image_url"] is not None:
        assert data["image_url"].startswith("/static/pictures/")

    # KHÔNG rò rỉ đáp án: các key/dữ liệu đáp án không xuất hiện trong raw response
    raw = json.dumps(data)
    assert "canonical_word" not in raw
    assert "accepted_answers" not in raw


def test_command_content_recognition_and_repetition(cleanup_test_users):
    token = _register_patient()
    items = _list_assignments(token, "command_identification")
    assert len(items) == 10

    modes_seen = set()
    for item in items:
        resp = client.get(
            f"/assignments/{item['assignment_id']}/content", headers=_auth(token)
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["exercise_type"] == "command_identification"
        assert data["mode"] in ("recognition", "repetition")
        modes_seen.add(data["mode"])

        if data["mode"] == "recognition":
            # Đủ 4 lựa chọn, mỗi lựa chọn có vocab_id + word, KHÔNG đánh dấu đáp án đúng
            assert len(data["choices"]) == 4
            for choice in data["choices"]:
                assert choice["vocab_id"]
                assert choice["word"]
                assert "is_correct" not in choice
                assert "correct" not in json.dumps(choice)
            # 4 vocab_id phải khác nhau
            ids = [c["vocab_id"] for c in data["choices"]]
            assert len(set(ids)) == 4
            assert data["command_text"]
        else:  # repetition
            assert data["prompt"] == "Nghe và nhắc lại"
            assert "choices" not in data

    # Plan 10 bài CMD thường có cả 2 mode; nếu chỉ 1 mode cũng không sai spec —
    # chỉ cần chắc chắn đã đi qua ít nhất 1 mode hợp lệ.
    assert modes_seen


def test_sentence_content_no_answer_leak(cleanup_test_users):
    token = _register_patient()
    items = _list_assignments(token, "sentence_building")
    assert len(items) == 10

    resp = client.get(
        f"/assignments/{items[0]['assignment_id']}/content", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["exercise_type"] == "sentence_building"
    assert data["template_display"]  # vd "Tôi muốn ăn ____"
    assert data["prompt"] == "Hoàn thành câu"

    raw = json.dumps(data)
    assert "full_sentence" not in raw
    assert "accepted_answers" not in raw

    # Đáp án thật (full_sentence trong DB) không được xuất hiện trong response
    db = SessionLocal()
    try:
        assignment = (
            db.query(ExerciseAssignment)
            .filter(ExerciseAssignment.id == uuid.UUID(items[0]["assignment_id"]))
            .first()
        )
        full_sentence = assignment.exercise.target_sentence_instance.full_sentence
    finally:
        db.close()
    assert full_sentence not in raw


def test_content_of_other_patient_403(cleanup_test_users):
    token_a = _register_patient()
    token_b = _register_patient()
    items_a = _list_assignments(token_a, "naming")

    resp = client.get(
        f"/assignments/{items_a[0]['assignment_id']}/content", headers=_auth(token_b)
    )
    assert resp.status_code == 403


# ── POST /assignments/{id}/submit — nhánh recognition (selected_vocab_id) ────

def _find_recognition_assignment(token: str) -> dict | None:
    """Tìm 1 assignment CMD mode recognition trong plan của patient (None nếu không có)."""
    for item in _list_assignments(token, "command_identification"):
        resp = client.get(
            f"/assignments/{item['assignment_id']}/content", headers=_auth(token)
        )
        if resp.status_code == 200 and resp.json().get("mode") == "recognition":
            return {"item": item, "content": resp.json()}
    return None


def test_submit_recognition_correct_answer(cleanup_test_users):
    token = _register_patient()
    found = _find_recognition_assignment(token)
    if found is None:
        pytest.skip("Plan không có bài CMD recognition nào (sampling ngẫu nhiên)")

    assignment_id = found["item"]["assignment_id"]
    # Lấy đáp án ĐÚNG từ DB (test được phép đọc DB — response thì không lộ)
    db = SessionLocal()
    try:
        assignment = (
            db.query(ExerciseAssignment)
            .filter(ExerciseAssignment.id == uuid.UUID(assignment_id))
            .first()
        )
        correct_vocab_id = str(assignment.exercise.target_vocab_id)
    finally:
        db.close()

    # Đáp án đúng PHẢI nằm trong 4 choices trả về cho UI (khớp seed với scoring)
    choice_ids = [c["vocab_id"] for c in found["content"]["choices"]]
    assert correct_vocab_id in choice_ids

    # Nộp bằng selected_vocab_id, KHÔNG gửi audio
    resp = client.post(
        f"/assignments/{assignment_id}/submit",
        data={"selected_vocab_id": correct_vocab_id},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["result"] == "correct"
    assert data["is_final"] is True

    # Sau khi nộp, bài phải chuyển "completed" trong danh sách
    items = _list_assignments(token, "command_identification")
    submitted = next(i for i in items if i["assignment_id"] == assignment_id)
    assert submitted["status"] == "completed"


def test_submit_recognition_wrong_answer(cleanup_test_users):
    token = _register_patient()
    found = _find_recognition_assignment(token)
    if found is None:
        pytest.skip("Plan không có bài CMD recognition nào (sampling ngẫu nhiên)")

    assignment_id = found["item"]["assignment_id"]
    db = SessionLocal()
    try:
        assignment = (
            db.query(ExerciseAssignment)
            .filter(ExerciseAssignment.id == uuid.UUID(assignment_id))
            .first()
        )
        correct_vocab_id = str(assignment.exercise.target_vocab_id)
    finally:
        db.close()

    wrong = next(
        c["vocab_id"] for c in found["content"]["choices"] if c["vocab_id"] != correct_vocab_id
    )
    resp = client.post(
        f"/assignments/{assignment_id}/submit",
        data={"selected_vocab_id": wrong},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"] == "incorrect"
