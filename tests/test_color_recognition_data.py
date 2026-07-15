"""
Test GĐ1 color_recognition — CHỈ dữ liệu + assets (chưa endpoint/chấm).
Ô màu vẽ từ HEX ở FE — chỉ audio được serve tĩnh.
"""

import re

from app.core.database import SessionLocal
from app.models.color_recognition import Color, ColorRecognitionExercise
from app.services.asset_url_service import color_instruction_audio_url

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def test_seed_counts_and_shapes():
    """Sau seed: 12 colors + 12 exercises; hex hợp lệ; FK đúng; level 1 toàn bộ."""
    db = SessionLocal()
    try:
        assert db.query(Color).count() == 12
        assert db.query(ColorRecognitionExercise).count() == 12

        for c in db.query(Color).all():
            assert c.color_id.startswith("COL")
            assert HEX_RE.match(c.hex_code), f"{c.name}: hex lạ {c.hex_code!r}"

        for ex in db.query(ColorRecognitionExercise).all():
            assert ex.exercise_code.startswith("CLR")
            assert ex.exercise_type == "color_recognition"
            assert ex.level == 1
            assert ex.target_color is not None
            assert isinstance(ex.suitable_profiles, list) and ex.suitable_profiles
            # instruction_audio khớp tên màu đích (red.wav hỏi màu đỏ)
            assert ex.instruction_audio == f"{ex.target_color.name}.wav"
    finally:
        db.close()


def test_color_audio_urls_resolve():
    """MỌI audio hỏi màu đều tồn tại trong media/color_audio -> URL không None."""
    db = SessionLocal()
    try:
        missing = [
            ex.instruction_audio
            for ex in db.query(ColorRecognitionExercise).all()
            if color_instruction_audio_url(ex.instruction_audio) is None
        ]
        assert not missing, f"Audio thiếu: {missing}"
        assert color_instruction_audio_url("red.wav") == "/static/color-audio/red.wav"
        assert color_instruction_audio_url("khong_co.wav") is None
    finally:
        db.close()
