"""
Test suite cho app.services.scoring_service

Gồm các test cho từng BLOCK của scoring pipeline:
- BLOCK 1: normalize_text, tokenize
- BLOCK 2: is_invalid_input
- BLOCK 3: component scorers (text_similarity, keyword_match, etc.)
- BLOCK 4 + 5: sub-scorers qua router
- BLOCK 6: classify
- BLOCK 7: progression (update_vocab_level, reset_session)
- BLOCK 8: apply_difficulty_weight
"""

import pytest

from app.services.scoring_service import (
    FLUENCY_FALLBACK,
    ProgressionState,
    ScoreResult,
    ScoringExercise,
    apply_difficulty_weight,
    classify,
    classifier_present,
    fluency_score,
    keyword_coverage,
    keyword_match,
    normalize_text,
    order_score,
    reset_session,
    score,
    text_similarity,
    tokenize,
    update_vocab_level,
)


# ==============================================================================
# HELPERS
# ==============================================================================


def _approx(a: float, b: float, tol: float = 0.5) -> bool:
    return abs(a - b) <= tol


# --- Fixtures: dữ liệu mẫu giống Asset.xlsx ---


def _ex_naming():
    return ScoringExercise(
        exercise_id="NAM001", exercise_type="naming", topic="đồ vật quen thuộc",
        vocab_level=1, canonical_word="cái kéo",
        accepted_answers=["kéo", "cây kéo", "cái kéo"],
        accepted_classifiers=["cái", "cây"], duration_expected=2.0)


def _ex_cmd2():
    return ScoringExercise(
        exercise_id="CMD002", exercise_type="command_identification",
        mode="repetition", topic="đồ vật quen thuộc", vocab_level=1,
        canonical_word="cái kéo", accepted_answers=["kéo", "cây kéo", "cái kéo"],
        accepted_classifiers=["cái", "cây"], duration_expected=2.0)


def _ex_cmd1():
    return ScoringExercise(
        exercise_id="CMD001", exercise_type="command_identification",
        mode="recognition", topic="đồ vật quen thuộc", vocab_level=1,
        target_vocab_id="V001", distractor_vocab_ids=["V002", "V003", "V004"])


def _ex_sen():
    return ScoringExercise(
        exercise_id="SEN001", exercise_type="sentence_building",
        topic="hoạt động thường ngày", vocab_level=1,
        full_sentence="tôi đang ăn cơm", missing_words=["ăn", "cơm"],
        duration_expected=2.0)


# ==============================================================================
# BLOCK 1: normalize_text, tokenize
# ==============================================================================


def test_normalize_basic():
    assert normalize_text("Cái Kéo!") == "cái kéo"
    assert normalize_text("  tôi   ăn  cơm  ") == "tôi ăn cơm"
    assert normalize_text("UỐNG NƯỚC.") == "uống nước"
    assert normalize_text("") == ""


def test_normalize_unicode_nfc():
    # "à" dạng tổ hợp (a + U+0300) phải bằng dạng precomposed
    decomposed = "àn"      # a + huyền + n  = "àn"
    precomposed = "àn"
    assert normalize_text(decomposed) == normalize_text(precomposed)


def test_tokenize():
    assert tokenize("tôi đang ăn cơm") == ["tôi", "đang", "ăn", "cơm"]
    assert tokenize("") == []


# ==============================================================================
# BLOCK 3: component scorers
# ==============================================================================


def test_text_similarity():
    assert text_similarity("cái kéo", "cái kéo") == 100.0
    assert _approx(text_similarity("kéo", "cái kéo"), 60.0, 1.0)
    assert _approx(text_similarity("cái kẹo", "cái kéo"), 85.71, 0.5)  # sai 1 âm -> vẫn cao
    assert text_similarity("con chó", "cái kéo") < 40                  # sai hẳn -> thấp


def test_keyword_match():
    answers = ["kéo", "cây kéo", "cái kéo"]
    assert keyword_match("cái kéo", answers) == 100.0
    assert keyword_match("kéo", answers) == 100.0
    assert keyword_match("đây là cái kéo", answers) == 100.0   # nói dư vẫn match
    assert keyword_match("con chó", answers) == 0.0


def test_keyword_coverage():
    missing = ["ăn", "cơm"]
    assert keyword_coverage("tôi đang ăn cơm", missing) == 100.0
    assert keyword_coverage("tôi đang ăn", missing) == 50.0
    assert keyword_coverage("tôi đang đi học", missing) == 0.0


def test_keyword_coverage_multiword_bugfix():
    # BUG FIX: cụm từ khuyết NHIỀU TỪ ("khoai lang") phải khớp khi nói đúng liền mạch.
    # Trước đây luôn trả 0 -> câu đúng hoàn toàn vẫn bị điểm thấp.
    assert keyword_coverage("tôi muốn ăn khoai lang", ["khoai lang"]) == 100.0
    assert keyword_coverage("tôi muốn ăn cơm", ["khoai lang"]) == 0.0
    # cụm phải LIỀN MẠCH đúng thứ tự (không phải chỉ có mặt rời rạc)
    assert keyword_coverage("lang khoai", ["khoai lang"]) == 0.0
    # trộn 1 cụm nhiều từ + 1 từ đơn
    assert keyword_coverage("mẹ nấu canh chua", ["canh chua", "mẹ"]) == 100.0


def test_classifier_present_bugfix():
    cls = ["cái", "cây"]
    assert classifier_present("cái kéo", cls) == 100.0
    assert classifier_present("cây kéo", cls) == 100.0
    assert classifier_present("kéo", cls) == 0.0          # thiếu loại từ
    assert classifier_present("tờ kéo", cls) == 0.0       # BUG FIX: "tờ" sai -> KHÔNG còn 100
    assert classifier_present("kéo", []) == 100.0          # vocab không cần loại từ


def test_order_score_values():
    # "đang" là stop word -> order chấm trên từ NỘI DUNG: [tôi, ăn, cơm]
    t = "tôi đang ăn cơm"
    assert order_score("tôi đang ăn cơm", t)["score"] == 100.0
    assert _approx(order_score("tôi đang cơm ăn", t)["score"], 83.33)   # đảo cơm/ăn
    assert order_score("tôi ăn cơm", t)["score"] == 100.0               # bớt "đang" -> không phạt
    assert _approx(order_score("cơm ăn đang tôi", t)["score"], 66.67)   # đảo lộn cả câu
    assert _approx(order_score("ăn cơm", t)["score"], 66.67)            # thiếu "tôi" (nội dung)
    assert order_score("đi học", t)["score"] == 0.0


def test_order_score_detail():
    # đếm trên từ NỘI DUNG [tôi, ăn, cơm]: tôi đúng, ăn đúng, cơm sai chỗ
    d = order_score("tôi cơm ăn", "tôi đang ăn cơm")
    assert (d["correct"], d["misplaced"], d["missing"]) == (2, 1, 0)


def test_order_score_stopword_tolerance():
    # Cải tiến cho ASR chưa finetune: chèn/thiếu TỪ ĐỆM không bị phạt; từ NỘI DUNG vẫn chấm chặt.
    t = "tôi đang ăn cơm"
    assert order_score("tôi ăn cơm", t)["score"] >= 90.0        # bớt 1 stop word
    assert order_score("tôi là ăn cơm", t)["score"] >= 90.0     # ASR chèn 1 stop word
    assert order_score("cái tôi đang ăn cơm", t)["score"] >= 90.0
    assert order_score("tôi ăn", t)["score"] <= 70.0            # thiếu từ nội dung "cơm" -> phạt rõ
    # target toàn stop words -> fallback so nguyên bản, không chia 0
    assert order_score("đã rồi", "đã rồi")["score"] == 100.0


def test_order_score_repeated_word():
    # Từ LẶP trong câu ("giờ" x2): nói đúng tuyệt đối phải được 100,
    # không bị index() trỏ về lần xuất hiện đầu rồi chấm oan "sai vị trí".
    t = "bây giờ là mười một giờ"
    assert order_score("bây giờ là mười một giờ", t)["score"] == 100.0
    d = order_score("bây giờ là mười một giờ", t)
    # từ nội dung = [bây, giờ, mười, giờ] ("là", "một" là stop words) — cả 4 đúng vị trí
    assert (d["correct"], d["misplaced"], d["missing"]) == (4, 0, 0)
    # thiếu chữ "giờ" cuối -> vẫn bị bắt thiếu
    assert order_score("bây giờ là mười một", t)["score"] < 100.0


def test_fluency():
    assert fluency_score(2.0, 2.0) == 100.0
    assert _approx(fluency_score(2.6, 2.0), 76.92, 0.5)
    assert fluency_score(5.0, 2.0) == 0.0      # chậm > gấp đôi -> 0
    assert fluency_score(0.8, 2.0) == 0.0      # nhanh > gấp đôi -> 0
    assert fluency_score(0, 2.0) == FLUENCY_FALLBACK


# ==============================================================================
# BLOCK 4 + 5: sub-scorers qua router
# ==============================================================================


def test_naming_pass():
    r = score(_ex_naming(), transcript="cái kéo", audio_duration=2.0, asr_confidence=0.9)
    assert r.components["keyword"] == 100.0
    assert r.components["classifier_present"] == 100.0
    assert r.result == "pass"
    assert _approx(r.score, 100.0, 1.0)


def test_naming_classifier_omission_still_pass():
    # "kéo" thiếu loại từ nhưng keyword đúng -> vẫn pass (partial credit)
    r = score(_ex_naming(), transcript="kéo", audio_duration=2.0, asr_confidence=0.9)
    assert r.components["keyword"] == 100.0
    assert r.components["classifier_present"] == 0.0
    assert r.result == "pass"


def test_naming_to_keo_bugfix():
    # "tờ kéo": keyword đúng (chứa "kéo") nhưng classifier sai -> điểm thấp hơn "cái kéo"
    r = score(_ex_naming(), transcript="tờ kéo", audio_duration=2.0, asr_confidence=0.9)
    assert r.components["classifier_present"] == 0.0
    # keyword 100*0.5 + sim ~61.5*0.25 + flu 100*0.15 + cls 0*0.10 = 50+15.4+15+0 ≈ 80.4
    assert r.result == "pass"
    assert r.score < 85   # thấp rõ so với "cái kéo" (~100)


def test_naming_wrong_word_retry():
    r = score(_ex_naming(), transcript="con chó", audio_duration=2.0, asr_confidence=0.9)
    assert r.components["keyword"] == 0.0
    assert r.result == "retry"


def test_cmd2_weights():
    r = score(_ex_cmd2(), transcript="cái kéo", audio_duration=2.0, asr_confidence=0.9)
    # 0.40*100 + 0.30*100 + 0.20*100 + 0.10*100 = 100
    assert _approx(r.score, 100.0, 0.5)
    assert r.result == "pass"


def test_cmd2_classifier_weight_heavier_than_nam():
    # thiếu loại từ ở CMD2 phạt nặng hơn NAM (20% vs 10%)
    nam = score(_ex_naming(), transcript="kéo", audio_duration=2.0, asr_confidence=0.9)
    cmd2 = score(_ex_cmd2(), transcript="kéo", audio_duration=2.0, asr_confidence=0.9)
    # cùng input "kéo": NAM mất 10% classifier, CMD2 mất 20% -> CMD2 thấp hơn
    assert cmd2.score < nam.score


def test_cmd1_correct_incorrect():
    correct = score(_ex_cmd1(), selected_vocab_id="V001")
    wrong = score(_ex_cmd1(), selected_vocab_id="V002")
    assert correct.score is None and correct.is_correct is True and correct.result == "correct"
    assert wrong.score is None and wrong.is_correct is False and wrong.result == "incorrect"


def test_sentence_full_correct():
    r = score(_ex_sen(), transcript="tôi đang ăn cơm", audio_duration=2.0, asr_confidence=0.9)
    # keyword 100, order 100, fluency 100 -> 0.4*100+0.5*100+0.1*100 = 100
    assert _approx(r.score, 100.0, 0.5)
    assert r.result == "pass"
    assert r.components["order_detail"]["missing"] == 0


def test_sentence_missing_keyword_near():
    # thiếu 1 từ khuyết -> keyword 50; order chấm trên [tôi, ăn, cơm] thiếu "cơm" -> 66.67
    r = score(_ex_sen(), transcript="tôi đang ăn", audio_duration=2.0, asr_confidence=0.9)
    assert r.components["keyword"] == 50.0
    assert _approx(r.components["order_score"], 66.67)
    # 0.4*50 + 0.5*66.67 + 0.1*100 = 63.33 -> near
    assert r.result == "near"


def test_sentence_wrong_action_retry():
    r = score(_ex_sen(), transcript="tôi đang đi học", audio_duration=2.0, asr_confidence=0.9)
    assert r.components["keyword"] == 0.0
    assert r.result == "retry"


def test_sentence_multiword_vocab_passes():
    # Tái hiện lỗi user báo: câu "Tôi muốn ăn ___" với vocab NHIỀU TỪ "khoai lang",
    # nói đúng hoàn toàn ở lần 1 -> phải PASS (trước bug: keyword=0 -> ~57 -> retry/near).
    ex = ScoringExercise(
        exercise_id="SEN_KL", exercise_type="sentence_building",
        topic="ăn uống", vocab_level=1,
        full_sentence="tôi muốn ăn khoai lang", missing_words=["khoai lang"],
        duration_expected=2.0)
    r = score(ex, transcript="tôi muốn ăn khoai lang", audio_duration=2.0,
              asr_confidence=0.9, attempt_number=1)
    assert r.components["keyword"] == 100.0
    assert r.components["order_score"] == 100.0
    assert _approx(r.score, 100.0, 0.5)
    assert r.result == "pass"


def test_sentence_retry_no_penalty():
    # BỎ phạt theo attempt: cùng transcript đúng, attempt 1 và attempt 2 phải BẰNG điểm.
    # attempt > 1 chỉ còn ghi used_fallback_audio để SLP thống kê.
    a1 = score(_ex_sen(), transcript="tôi đang ăn cơm", audio_duration=2.0,
               asr_confidence=0.9, attempt_number=1)
    a2 = score(_ex_sen(), transcript="tôi đang ăn cơm", audio_duration=2.0,
               asr_confidence=0.9, attempt_number=2)
    assert a2.score == a1.score
    assert a2.score == a2.raw_score
    assert a1.used_fallback_audio is False
    assert a2.used_fallback_audio is True


def test_sentence_no_attempt_penalty_user_case():
    # Ca user báo: "Đây là điện thoại", nói đúng hoàn toàn ở lần thử 11.
    # Trước khi sửa: raw ~97 × 0.60 = ~58 (near). Sau khi sửa: >= 80 và PASS.
    ex = ScoringExercise(
        exercise_id="SEN_DT", exercise_type="sentence_building",
        topic="đồ vật quen thuộc", vocab_level=1,
        full_sentence="Đây là điện thoại", missing_words=["điện thoại"])
    r = score(ex, transcript="đây là điện thoại", audio_duration=2.0,
              asr_confidence=0.9, attempt_number=11)
    assert r.score >= 80
    assert r.score == r.raw_score
    assert r.result == "pass"
    assert r.used_fallback_audio is True   # vẫn ghi nhận có thử lại (thống kê)


# ==============================================================================
# BLOCK 2: input gate
# ==============================================================================


def test_input_gate():
    ex = _ex_naming()
    assert score(ex, transcript="cái kéo", audio_duration=0.2, asr_confidence=0.9).result == "invalid"
    assert score(ex, transcript="", audio_duration=2.0, asr_confidence=0.9).result == "invalid"
    assert score(ex, transcript="cái kéo", audio_duration=2.0, asr_confidence=0.2).result == "invalid"


# ==============================================================================
# BLOCK 6: classify
# ==============================================================================


def test_classify():
    assert classify(75.0) == "pass"
    assert classify(60.0) == "near"
    assert classify(40.0) == "retry"


# ==============================================================================
# BLOCK 8: difficulty weighting
# ==============================================================================


def test_difficulty_weight():
    assert apply_difficulty_weight(75, 1) == 75.0
    assert apply_difficulty_weight(75, 2) == 86.25
    assert apply_difficulty_weight(75, 3) == 97.5
    assert apply_difficulty_weight(None, 3) is None


# ==============================================================================
# BLOCK 7: progression (in-session)
# ==============================================================================


def test_progression_level_up_3_correct():
    st = ProgressionState()
    topic = "ăn uống"
    r1 = update_vocab_level(st, "pass", topic)
    assert r1 == {"action": "hold", "vocab_level": 1, "correct_streak": 1}
    update_vocab_level(st, "pass", topic)
    r3 = update_vocab_level(st, "pass", topic)
    assert r3["action"] == "level_up" and r3["vocab_level"] == 2 and r3["correct_streak"] == 0


def test_progression_mixed_types_count():
    # CMD recognition "correct" cũng tính vào streak như "pass"
    st = ProgressionState()
    topic = "ăn uống"
    update_vocab_level(st, "pass", topic)       # NAM pass
    update_vocab_level(st, "correct", topic)    # CMD1 correct
    r = update_vocab_level(st, "pass", topic)   # SEN pass
    assert r["action"] == "level_up"


def test_progression_near_resets_streak():
    st = ProgressionState()
    topic = "ăn uống"
    update_vocab_level(st, "pass", topic)
    update_vocab_level(st, "pass", topic)
    update_vocab_level(st, "near", topic)       # đứt chuỗi
    assert st.correct_streak == 0 and st.vocab_level == 1


def test_progression_topic_change_resets():
    st = ProgressionState()
    update_vocab_level(st, "pass", "ăn uống")
    update_vocab_level(st, "pass", "ăn uống")
    r = update_vocab_level(st, "pass", "gia đình")   # đổi topic -> chuỗi đứt, chỉ còn 1
    assert r["action"] == "hold" and st.correct_streak == 1


def test_progression_max_level():
    st = ProgressionState(vocab_level=3)
    for _ in range(3):
        r = update_vocab_level(st, "pass", "ăn uống")
    assert st.vocab_level == 3 and r["action"] == "hold"   # không vượt 3


def test_session_reset():
    st = ProgressionState(vocab_level=3, correct_streak=2, current_topic="ăn uống")
    reset_session(st)
    assert st.vocab_level == 1 and st.correct_streak == 0 and st.current_topic is None
