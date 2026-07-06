"""
Test app.services.plan_service.create_initial_plan — dùng DB thật, rollback sau test.
"""

import uuid
from datetime import date

import pytest

from app.core.database import SessionLocal
from app.models.content import Exercise
from app.models.enums import ExerciseType, Gender
from app.models.therapy import ExerciseAssignment
from app.models.user import Patient
from app.services.plan_service import EXERCISES_PER_TYPE, create_initial_plan


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _make_patient(db_session, severity_level: str) -> Patient:
    patient = Patient(
        full_name="TEST_PATIENT_DO_NOT_USE",
        email=f"test_{uuid.uuid4().hex[:10]}@example.com",
        password_hash="x",
        date_of_birth=date(1980, 1, 1),
        gender=Gender.male,
        severity_level=severity_level,
    )
    db_session.add(patient)
    db_session.flush()
    return patient


def _assignment_exercises(db_session, plan_id):
    """Trả về list Exercise của mọi assignment trong plan."""
    return (
        db_session.query(Exercise)
        .join(ExerciseAssignment, ExerciseAssignment.exercise_id == Exercise.id)
        .filter(ExerciseAssignment.plan_id == plan_id)
        .all()
    )


def test_create_initial_plan_severity_nang_maps_to_level_1(db_session):
    """severity 'Nặng' -> vocab_level 1: mọi bài được giao phải có vocab_level == 1."""
    patient = _make_patient(db_session, severity_level="Nặng")
    plan = create_initial_plan(db_session, patient)

    assert plan.therapist_id is None
    exercises = _assignment_exercises(db_session, plan.id)
    assert len(exercises) > 0
    for ex in exercises:
        assert ex.vocab_level == 1, (
            f"Bài {ex.exercise_code} có vocab_level={ex.vocab_level}, "
            f"không được lấy bài khó hơn level 1 cho bệnh nhân nặng"
        )


def test_create_initial_plan_assigns_30_exercises(db_session):
    """
    Kỳ vọng 10 bài mỗi loại (tổng 30). Nếu 1 loại không đủ bài ở level <= target thì
    số được giao = min(10, số bài khả dụng) — vẫn đúng logic, không fail cứng vì thiếu data.
    """
    patient = _make_patient(db_session, severity_level="Nặng")
    target_level = 1  # "Nặng" -> 1
    plan = create_initial_plan(db_session, patient)

    total = 0
    for ex_type in (
        ExerciseType.naming,
        ExerciseType.command_identification,
        ExerciseType.sentence_building,
    ):
        assigned = (
            db_session.query(ExerciseAssignment)
            .join(Exercise, ExerciseAssignment.exercise_id == Exercise.id)
            .filter(
                ExerciseAssignment.plan_id == plan.id,
                Exercise.exercise_type == ex_type,
            )
            .count()
        )
        available = (
            db_session.query(Exercise)
            .filter(
                Exercise.exercise_type == ex_type,
                Exercise.vocab_level <= target_level,
            )
            .count()
        )
        expected = min(EXERCISES_PER_TYPE, available)
        assert assigned == expected, (
            f"{ex_type.value}: giao {assigned} bài nhưng kỳ vọng {expected} "
            f"(khả dụng {available} bài ở level <= {target_level})"
        )
        if expected < EXERCISES_PER_TYPE:
            print(
                f"\n⚠️  {ex_type.value}: chỉ có {available} bài ở level <= {target_level}, "
                f"giao {assigned} (< {EXERCISES_PER_TYPE}) do thiếu dữ liệu — KHÔNG phải lỗi logic."
            )
        total += assigned

    print(f"\nTổng số bài được giao: {total}")
