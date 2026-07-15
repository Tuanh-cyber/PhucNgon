"""
Test GIAI ĐOẠN 1 của dạng bài logic_sequence — CHỈ dữ liệu + assets (chưa endpoint/chấm).

Phủ: seed đúng số lượng (13 sequences / 50 steps / 13 exercises), quan hệ FK đúng,
URL builder chỉ trả URL khi file thật tồn tại trong media/sequence/.
"""

from app.core.database import SessionLocal
from app.models.sequence import LogicSequenceExercise, Sequence, SequenceStep
from app.services.asset_url_service import instruction_audio_url, sequence_image_url


def test_seed_counts_match_expectation():
    """Sau seed: 13 sequences, 50 steps, 13 exercises; step_count khớp số step thật."""
    db = SessionLocal()
    try:
        assert db.query(Sequence).count() == 13
        assert db.query(SequenceStep).count() == 50
        assert db.query(LogicSequenceExercise).count() == 13

        # Phân bố level đúng rule.md: L1=3 bước, L2=4 bước, L3=5 bước
        for seq in db.query(Sequence).all():
            assert seq.step_count == len(seq.steps)
            expected_steps = {1: 3, 2: 4, 3: 5}[seq.level]
            assert seq.step_count == expected_steps, f"{seq.sequence_id} lệch số bước"
            # step_order liên tục 1..N (nền tảng cho chấm nhị phân so thứ tự ở GĐ2)
            assert [s.step_order for s in seq.steps] == list(range(1, seq.step_count + 1))

        # Mỗi exercise trỏ 1 sequence có thật + đúng loại
        for ex in db.query(LogicSequenceExercise).all():
            assert ex.exercise_type == "logic_sequence"
            assert ex.exercise_code.startswith("SEQ")
            assert ex.target_sequence is not None
            assert isinstance(ex.suitable_profiles, list) and ex.suitable_profiles
    finally:
        db.close()


def test_sequence_asset_urls_resolve():
    """URL builder trả đúng /static/sequence/... và MỌI ảnh + audio đều tồn tại trên đĩa."""
    db = SessionLocal()
    try:
        missing = []
        for step in db.query(SequenceStep).all():
            url = sequence_image_url(step)
            if url is None:
                missing.append(f"level{step.sequence.level}/{step.image_file}")
            else:
                assert url.startswith("/static/sequence/level")
        assert not missing, f"Ảnh thiếu trên đĩa: {missing}"

        audio = instruction_audio_url()
        assert audio == "/static/sequence/instruction_audio.wav"
    finally:
        db.close()
