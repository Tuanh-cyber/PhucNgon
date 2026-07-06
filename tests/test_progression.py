"""
Test progression lên level theo topic (rule.md mục 2, bảng topic_progress).

Chiến lược:
  - Luật đếm/lên level test qua _update_topic_progress() với score ĐIỀU KHIỂN ĐƯỢC
    (không phụ thuộc scoring engine — engine đã có test riêng).
  - 1 test tích hợp qua submit_attempt() (ASR monkeypatch) xác nhận dây đã nối:
    nộp bài graded -> TopicProgress được tạo/cập nhật + response có leveled_up/new_level.

Cleanup: xoá plan + user test (topic_progress cascade theo patients ON DELETE CASCADE).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.content import Exercise
from app.models.enums import ExerciseType
from app.models.therapy import ExerciseAssignment, TherapyPlan, TopicProgress
from app.models.user import Patient, User
from app.services import asr_service
from app.services.session_service import _update_topic_progress, submit_attempt
from tests.test_audio_service import _make_wav

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


def _register_patient() -> str:
    email = f"test_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/auth/register/patient",
        json={
            "full_name": "TEST_PATIENT_DO_NOT_USE",
            "email": email,
            "password": "secret123",
            "date_of_birth": "1980-01-01",
            "gender": "male",
            "severity_level": "Nặng",  # -> vocab_level khởi đầu 1
        },
    )
    assert resp.status_code == 201, resp.text
    return email


def _get_naming_setup(db, email):
    """Trả (patient, plan, exercise naming đầu tiên trong plan)."""
    patient = db.query(Patient).filter(Patient.email == email).first()
    assignment = (
        db.query(ExerciseAssignment)
        .join(TherapyPlan, ExerciseAssignment.plan_id == TherapyPlan.id)
        .join(Exercise, ExerciseAssignment.exercise_id == Exercise.id)
        .filter(
            TherapyPlan.patient_id == patient.id,
            Exercise.exercise_type == ExerciseType.naming,
        )
        .first()
    )
    assert assignment is not None
    return patient, assignment.plan, assignment.exercise


def test_three_high_scores_level_up_and_new_assignments(cleanup_test_data):
    """3 lần liên tiếp score>=80 cùng topic -> level 1->2, counter reset, giao thêm bài mới."""
    email = _register_patient()
    db = SessionLocal()
    try:
        patient, plan, exercise = _get_naming_setup(db, email)
        before_count = (
            db.query(ExerciseAssignment).filter(ExerciseAssignment.plan_id == plan.id).count()
        )

        r1 = _update_topic_progress(db, patient, exercise, plan, score_value=85.0)
        r2 = _update_topic_progress(db, patient, exercise, plan, score_value=90.0)
        assert r1 == {"leveled_up": False, "new_level": None}
        assert r2 == {"leveled_up": False, "new_level": None}

        r3 = _update_topic_progress(db, patient, exercise, plan, score_value=80.0)  # >= 80 tính
        assert r3 == {"leveled_up": True, "new_level": 2}

        progress = (
            db.query(TopicProgress)
            .filter(
                TopicProgress.patient_id == patient.id,
                TopicProgress.topic == exercise.topic,
            )
            .one()
        )
        assert progress.current_level == 2
        assert progress.consecutive_high_scores == 0  # reset sau khi lên level

        # Đã giao thêm bài mới (cùng loại + topic, level 2) vào plan
        after_count = (
            db.query(ExerciseAssignment).filter(ExerciseAssignment.plan_id == plan.id).count()
        )
        assert after_count > before_count

        db.commit()
    finally:
        db.close()


def test_low_score_resets_counter(cleanup_test_data):
    """2 lần >=80 rồi 1 lần <80 -> counter về 0, level GIỮ NGUYÊN; sau đó cần đủ 3 lần mới."""
    email = _register_patient()
    db = SessionLocal()
    try:
        patient, plan, exercise = _get_naming_setup(db, email)

        _update_topic_progress(db, patient, exercise, plan, score_value=85.0)
        _update_topic_progress(db, patient, exercise, plan, score_value=95.0)
        r = _update_topic_progress(db, patient, exercise, plan, score_value=60.0)  # < 80
        assert r == {"leveled_up": False, "new_level": None}

        progress = (
            db.query(TopicProgress)
            .filter(
                TopicProgress.patient_id == patient.id,
                TopicProgress.topic == exercise.topic,
            )
            .one()
        )
        assert progress.consecutive_high_scores == 0
        assert progress.current_level == 1

        # Cần lại đủ 3 lần liên tiếp mới lên level (2 lần đầu KHÔNG được tính lại)
        _update_topic_progress(db, patient, exercise, plan, score_value=88.0)
        _update_topic_progress(db, patient, exercise, plan, score_value=88.0)
        r = _update_topic_progress(db, patient, exercise, plan, score_value=88.0)
        assert r == {"leveled_up": True, "new_level": 2}

        db.commit()
    finally:
        db.close()


def test_level_caps_at_3(cleanup_test_data):
    """current_level không vượt quá 3 dù tiếp tục điểm cao."""
    email = _register_patient()
    db = SessionLocal()
    try:
        patient, plan, exercise = _get_naming_setup(db, email)
        # 2 vòng x3 lần -> level 3; thêm 3 lần nữa -> vẫn 3, không leveled_up
        for _ in range(6):
            _update_topic_progress(db, patient, exercise, plan, score_value=90.0)
        results = [
            _update_topic_progress(db, patient, exercise, plan, score_value=90.0)
            for _ in range(3)
        ]
        assert all(r["leveled_up"] is False for r in results)

        progress = (
            db.query(TopicProgress)
            .filter(
                TopicProgress.patient_id == patient.id,
                TopicProgress.topic == exercise.topic,
            )
            .one()
        )
        assert progress.current_level == 3
        db.commit()
    finally:
        db.close()


def test_submit_attempt_wires_progression(cleanup_test_data, monkeypatch):
    """Tích hợp: nộp bài graded qua submit_attempt -> TopicProgress được tạo cho topic đó
    và return có progression dict đúng hình dạng."""
    email = _register_patient()
    db = SessionLocal()
    try:
        patient, plan, exercise = _get_naming_setup(db, email)
        assignment = (
            db.query(ExerciseAssignment)
            .filter(
                ExerciseAssignment.plan_id == plan.id,
                ExerciseAssignment.exercise_id == exercise.id,
            )
            .first()
        )
        canonical_word = exercise.target_vocab.canonical_word
        monkeypatch.setattr(
            asr_service,
            "transcribe_audio",
            lambda wav_bytes: {"transcript": canonical_word, "confidence": 0.9},
        )

        wav = _make_wav(duration_s=2.0, amplitude=8000)
        saved, _, progression = submit_attempt(db, patient, assignment.id, wav_bytes=wav)
        assert saved.result.value == "pass"  # graded -> progression đã được cập nhật
        assert set(progression.keys()) == {"leveled_up", "new_level"}

        progress = (
            db.query(TopicProgress)
            .filter(
                TopicProgress.patient_id == patient.id,
                TopicProgress.topic == exercise.topic,
            )
            .one_or_none()
        )
        assert progress is not None
        # score >= 80 -> counter 1; < 80 -> counter 0. Cả 2 đều hợp lệ tuỳ điểm thật.
        expected = 1 if (saved.score or 0) >= 80 else 0
        assert progress.consecutive_high_scores == expected
    finally:
        db.close()
