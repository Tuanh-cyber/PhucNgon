"""
================================================================================
 PhụcNgôn — SCORING ENGINE  (MVP Phase 1)
================================================================================
 Owner: Nam  |  Module 3 (Scoring) + Module 4 (Rule Engine)

 File này hiện thực toàn bộ logic chấm điểm đã chốt trong bản
 "Scoring Engine Technical Spec". Mục tiêu: bàn giao cho team dùng trực tiếp.

 ------------------------------------------------------------------------------
 CHẠY FILE NÀY:
     python phucngon_scoring.py          # chạy toàn bộ test suite (in kết quả)
     pytest phucngon_scoring.py          # nếu team đã cài pytest
 ------------------------------------------------------------------------------
 PHỤ THUỘC:
     - KHÔNG cần thư viện ngoài để chạy (dùng difflib + unicodedata chuẩn).
     - PRODUCTION: có thể thay 2 chỗ (đánh dấu [SWAP]) để tăng chất lượng:
         * difflib.SequenceMatcher  ->  python-Levenshtein (.ratio)  (nhanh hơn)
         * tokenize() whitespace    ->  underthesea.word_tokenize     (tách từ ghép tốt hơn)
       Logic không đổi, chỉ đổi engine bên dưới.
 ==============================================================================

 SƠ ĐỒ LUỒNG DỮ LIỆU (đọc từ trên xuống):

   [Frontend gửi lên]
        transcript (ASR)  |  selected_vocab_id (touch)  |  audio_duration
              │
              ▼
   ┌─────────────────────────────────────────────────────────┐
   │ BLOCK 1: normalize_text()   chuẩn hóa transcript          │
   └─────────────────────────────────────────────────────────┘
              │
              ▼
   ┌─────────────────────────────────────────────────────────┐
   │ BLOCK 2: input gate (is_invalid_input)                    │
   │   audio quá ngắn / rỗng / confidence thấp -> REJECT        │
   └─────────────────────────────────────────────────────────┘
              │ (hợp lệ)
              ▼
   ┌─────────────────────────────────────────────────────────┐
   │ BLOCK 3: các hàm tính thành phần (component scorers)      │
   │   text_similarity · keyword · classifier · order · fluency│
   └─────────────────────────────────────────────────────────┘
              │
              ▼
   ┌─────────────────────────────────────────────────────────┐
   │ BLOCK 4: 4 sub-scorer theo exercise_type                  │
   │   NAM · CMD-recognition · CMD-repetition · SEN            │
   └─────────────────────────────────────────────────────────┘
              │
              ▼
   ┌─────────────────────────────────────────────────────────┐
   │ BLOCK 5: router score()  -> chọn sub-scorer               │
   └─────────────────────────────────────────────────────────┘
              │
              ▼  raw score 0-100  (hoặc Correct/Incorrect cho CMD1)
   ┌─────────────────────────────────────────────────────────┐
   │ BLOCK 6: classify()  -> pass / near / retry               │
   └─────────────────────────────────────────────────────────┘
              │
              ▼
   ┌─────────────────────────────────────────────────────────┐
   │ BLOCK 7: progression  -> vocab level trong-session        │
   │ BLOCK 8: difficulty weighting -> điểm cho SLP dashboard   │
   └─────────────────────────────────────────────────────────┘
              │
              ▼
        ScoreResult (JSON) -> lưu DB + trả Frontend + SLP dashboard
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher
from typing import Optional


# ==============================================================================
# CONSTANTS — Các ngưỡng & trọng số đã chốt trong spec
# ==============================================================================
# Mọi con số "ma thuật" gom về đây để team chỉnh 1 chỗ, không rải khắp code.

# --- Ngưỡng phân loại kết quả (BLOCK 6) ---
PASS_THRESHOLD = 70      # score >= 70  -> PASS
NEAR_THRESHOLD = 50      # 50 <= score < 70 -> NEAR ; < 50 -> RETRY

# --- Input gate (BLOCK 2) ---
MIN_AUDIO_DURATION = 0.5   # giây — ngắn hơn coi như không nói
MIN_ASR_CONFIDENCE = 0.4   # confidence thấp hơn -> không chấm, yêu cầu nói lại

# --- Fluency (BLOCK 3) ---
FLUENCY_MIN_RATIO = 0.5    # ratio < 0.5 (nhanh/chậm gấp đôi) -> fluency = 0
FLUENCY_FALLBACK = 70.0    # khi thiếu dữ liệu duration -> điểm mặc định

# --- Trọng số NAM (BLOCK 4) ---
W_NAM = {"keyword": 0.50, "similarity": 0.25, "fluency": 0.15, "classifier": 0.10}

# --- Trọng số CMD Mode 2 / Repetition (BLOCK 4) ---
W_CMD2 = {"keyword": 0.40, "similarity": 0.30, "classifier": 0.20, "fluency": 0.10}

# --- Trọng số SEN / Sentence Building (BLOCK 4) ---
W_SEN = {"keyword": 0.40, "order": 0.50, "fluency": 0.10}

# --- order_score: điểm cho từng loại từ (BLOCK 3) ---
ORDER_CORRECT_WEIGHT = 1.0   # từ đúng vị trí
ORDER_MISPLACED_WEIGHT = 0.5 # từ có nói nhưng sai vị trí
# (từ thiếu = 0, tự bị phạt qua mẫu số = tổng số từ target)

# --- SEN fallback: nghe audio mẫu rồi nói lại -> nhân hệ số giảm (BLOCK 4) ---
ATTEMPT_MULTIPLIER = {1: 1.00, 2: 0.75, 3: 0.60}

# --- Progression: vocab level trong-session (BLOCK 7) ---
CORRECT_STREAK_TO_LEVEL_UP = 3   # 3 bài đúng liên tiếp cùng topic -> +1 level
MAX_VOCAB_LEVEL = 3
MIN_VOCAB_LEVEL = 1

# --- Difficulty weighting cho SLP dashboard (BLOCK 8) ---
DIFFICULTY_MULTIPLIER = {1: 1.00, 2: 1.15, 3: 1.30}

# --- Hư từ thì/thể tiếng Việt (tham khảo, dùng nếu cần mở rộng) ---
TENSE_PARTICLES = {"đã", "đang", "sẽ", "mới", "rồi", "xong", "vừa"}


# ==============================================================================
# DATA MODELS — Cấu trúc dữ liệu vào/ra
# ==============================================================================

@dataclass
class Exercise:
    """
    MÔ TẢ: Một bài tập, dữ liệu lấy từ Exercise_bank.xlsx + Asset.xlsx.
           Backend (Tuấn Anh) load từ DB rồi dựng object này trước khi chấm.

    DÙNG Ở ĐÂU: là input cho mọi sub-scorer.

    GHI CHÚ field theo loại bài (field nào không dùng để None / rỗng):
      - NAM           : canonical_word, accepted_answers, accepted_classifiers
      - CMD recognition: target_vocab_id, distractor_vocab_ids  (KHÔNG cần ASR)
      - CMD repetition : canonical_word, accepted_answers, accepted_classifiers
      - SEN           : full_sentence, missing_words
      - Tất cả        : duration_expected (từ TTS pre-generated), vocab_level, topic
    """
    exercise_id: str
    exercise_type: str                       # "naming" | "command_identification" | "sentence_building"
    topic: str
    vocab_level: int = 1                      # 1-3, level hiện tại trong session
    mode: Optional[str] = None               # None | "recognition" | "repetition"

    # --- NAM / CMD repetition ---
    canonical_word: str = ""                 # dạng chuẩn của từ, vd "cái kéo"
    accepted_answers: list[str] = field(default_factory=list)       # vd ["kéo","cây kéo","cái kéo"]
    accepted_classifiers: list[str] = field(default_factory=list)   # vd ["cái","cây"]  (BUG FIX: thay CLASSIFIER_MAP)

    # --- SEN ---
    full_sentence: str = ""                  # câu đầy đủ, vd "tôi đang ăn cơm"
    missing_words: list[str] = field(default_factory=list)          # phần khuyết, vd ["ăn","cơm"]

    # --- CMD recognition ---
    target_vocab_id: str = ""
    distractor_vocab_ids: list[str] = field(default_factory=list)

    # --- Chung ---
    duration_expected: float = 0.0           # giây, từ TTS chuẩn của bài


@dataclass
class ScoreResult:
    """
    MÔ TẢ: Kết quả chấm 1 lượt làm bài. Đây là object trả về Frontend +
           lưu vào bảng session_items + đẩy lên SLP dashboard.

    DÙNG Ở ĐÂU:
      - score / result          -> Rule Engine (progression) + Frontend UX
      - is_correct              -> chỉ CMD recognition
      - weighted_score          -> SLP dashboard (tiến bộ theo độ khó)
      - components              -> SLP dashboard (phân tích bệnh nhân yếu ở đâu)
    """
    exercise_id: str
    exercise_type: str
    mode: Optional[str]
    vocab_level: int
    topic: str

    # Score (CMD recognition: score=None, dùng is_correct)
    score: Optional[float]                    # adjusted score 0-100 (đã nhân attempt multiplier với SEN)
    raw_score: Optional[float]                # score attempt 1 (trước attempt multiplier)
    weighted_score: Optional[float]           # raw_score × difficulty_multiplier (cho SLP)
    is_correct: Optional[bool]                # chỉ CMD recognition

    components: dict                          # điểm từng thành phần (để SLP phân tích)
    result: str                               # "pass"|"near"|"retry"|"skip"|"correct"|"incorrect"|"invalid"

    attempt_number: int = 1
    used_fallback_audio: bool = False

    transcript: Optional[str] = None
    selected_vocab_id: Optional[str] = None
    audio_duration_s: Optional[float] = None
    asr_confidence: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ==============================================================================
# BLOCK 1 — TEXT NORMALIZATION
# ==============================================================================

def normalize_text(text: str) -> str:
    """
    INPUT : text thô (transcript từ ASR, hoặc target từ Asset).
    OUTPUT: chuỗi đã chuẩn hóa, sẵn sàng để so sánh.
    DÙNG TIẾP: mọi hàm so chuỗi (similarity, keyword, order...) gọi hàm này TRƯỚC.

    Các bước:
      1. Unicode NFC  — gộp dấu tiếng Việt về dạng precomposed.
                        (BẪY: ASR có thể trả "à" dạng a + dấu huyền rời = 2 ký tự;
                         NFC gộp thành 1 ký tự, nếu không 2 chuỗi "giống" lại bị tính khác.)
      2. lowercase
      3. xóa dấu câu .,!? (giữ chữ + dấu tiếng Việt nhờ flag UNICODE)
      4. gộp khoảng trắng thừa
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(text: str) -> list[str]:
    """
    INPUT : text (sẽ được normalize bên trong).
    OUTPUT: list từ.
    DÙNG TIẾP: keyword_score, order_score, classifier check.

    [SWAP] MVP dùng whitespace split (tiếng Việt tách theo âm tiết là đủ cho
           các target ngắn). PRODUCTION: thay bằng underthesea.word_tokenize
           để gộp từ ghép ("đánh răng" -> 1 token) chính xác hơn.
    """
    norm = normalize_text(text)
    return norm.split() if norm else []


# ==============================================================================
# BLOCK 2 — INPUT GATE  (chặn input rác trước khi chấm)
# ==============================================================================

def is_invalid_input(transcript: str, audio_duration: float,
                     asr_confidence: float) -> Optional[str]:
    """
    INPUT : transcript, audio_duration (giây), asr_confidence (0-1) — từ ASR module.
    OUTPUT: None nếu hợp lệ; ngược lại trả MÃ LỖI (str) để Frontend hiển thị.
    DÙNG TIẾP: router score() gọi đầu tiên; nếu có lỗi -> trả ScoreResult invalid,
               KHÔNG tính điểm và KHÔNG tính vào progression.

    Lưu ý: chỉ áp dụng cho bài có ASR. CMD recognition (touch) bỏ qua gate này.
    """
    if audio_duration is not None and audio_duration < MIN_AUDIO_DURATION:
        return "AUDIO_TOO_SHORT"          # "Hãy nói to và rõ hơn nhé!"
    if transcript is None or normalize_text(transcript) == "":
        return "EMPTY_TRANSCRIPT"          # "Chưa nghe thấy gì, thử lại nhé!"
    if asr_confidence is not None and asr_confidence < MIN_ASR_CONFIDENCE:
        return "LOW_CONFIDENCE"            # "Hệ thống chưa nghe rõ, nói lại nhé!"
    return None


# ==============================================================================
# BLOCK 3 — COMPONENT SCORERS  (các viên gạch dùng chung)
# ==============================================================================

def text_similarity(transcript: str, target: str) -> float:
    """
    INPUT : transcript bệnh nhân, target chuẩn (canonical_word hoặc full_sentence).
    OUTPUT: 0-100, độ giống nhau ở cấp KÝ TỰ.
    DÙNG Ở: NAM, CMD repetition. (KHÔNG dùng cho SEN — câu dài thì order_score thay thế.)

    Cách tính: SequenceMatcher.ratio() — bắt được lỗi phát âm cấp âm tiết
               (vd "kéo" vs "kẹo" ra ~67%, không phải 0).
    [SWAP] PRODUCTION: Levenshtein.ratio(normalize(a), normalize(b)) cho kết quả
           tương đương nhưng nhanh hơn nhiều khi scale.
    """
    a, b = normalize_text(transcript), normalize_text(target)
    if not a and not b:
        return 100.0
    if not a or not b:
        return 0.0
    return round(SequenceMatcher(None, a, b).ratio() * 100, 2)


def keyword_match(transcript: str, accepted_answers: list[str]) -> float:
    """
    INPUT : transcript, accepted_answers (list từ Asset, vd ["kéo","cái kéo"]).
    OUTPUT: 100 nếu transcript chứa BẤT KỲ đáp án nào; 0 nếu không.
    DÙNG Ở: NAM, CMD repetition. Đây là thành phần "có gọi đúng tên không".

    Match kiểu "chứa" (substring trên chuỗi đã normalize) để chấp nhận bệnh nhân
    nói dư ("đây là cái kéo" vẫn chứa "cái kéo").
    """
    norm_trans = normalize_text(transcript)
    if not norm_trans:
        return 0.0
    for ans in accepted_answers:
        norm_ans = normalize_text(ans)
        if norm_ans and norm_ans in norm_trans:
            return 100.0
    return 0.0


def keyword_coverage(transcript: str, missing_words: list[str]) -> float:
    """
    INPUT : transcript, missing_words (phần khuyết của câu SEN, vd ["ăn","cơm"]).
    OUTPUT: 0-100 = % từ khuyết được nói đủ (KHÔNG xét thứ tự — thứ tự để order_score lo).
    DÙNG Ở: SEN. Đây là thành phần "có nhận ra hành động / nói được từ khuyết không".
    """
    if not missing_words:
        return 100.0
    trans_tokens = set(tokenize(transcript))
    matched = [w for w in missing_words if normalize_text(w) in trans_tokens]
    return round(len(matched) / len(missing_words) * 100, 2)


def classifier_present(transcript: str, accepted_classifiers: list[str]) -> float:
    """
    INPUT : transcript, accepted_classifiers (loại từ ĐÚNG của vocab này, vd ["cái","cây"]).
    OUTPUT: 100 nếu transcript chứa loại từ đúng; 0 nếu thiếu HOẶC dùng sai loại từ.
    DÙNG Ở: NAM, CMD repetition.

    BUG FIX quan trọng: KHÔNG dùng map theo word_type (cách cũ khiến "tờ kéo" được 100
    vì "tờ" là loại từ hợp lệ chung). Ở đây chỉ chấp nhận loại từ nằm trong
    accepted_classifiers riêng của vocab -> "tờ" cho "cái kéo" => 0.

    Nếu accepted_classifiers rỗng (verb/adj không cần loại từ) -> trả 100 (không phạt).
    """
    if not accepted_classifiers:
        return 100.0
    tokens = set(tokenize(transcript))
    accepted = {normalize_text(c) for c in accepted_classifiers}
    return 100.0 if (tokens & accepted) else 0.0


def order_score(transcript: str, target: str) -> dict:
    """
    INPUT : transcript, target (full_sentence của bài SEN).
    OUTPUT: dict { "score": 0-100, "correct": n, "misplaced": n, "missing": n }
            -> score dùng cho công thức SEN; 3 con số kia đẩy lên SLP dashboard
               để bác sĩ biết bệnh nhân "thiếu từ" hay "đảo thứ tự".
    DÙNG Ở: SEN. Thay cho text_similarity vì câu dài cần phân tích cấu trúc.

    THUẬT TOÁN (tự thiết kế, không có lib sẵn):
      Duyệt từng từ target theo thứ tự, tìm VỊ TRÍ ĐẦU TIÊN của nó trong câu bệnh nhân.
        - không tìm thấy            -> missing
        - là từ đầu tiên, HOẶC vị trí > vị trí từ target trước đó  -> correct (đúng thứ tự)
        - tìm thấy nhưng đứng trước  -> misplaced (có nói nhưng sai chỗ)
      score = (correct×1.0 + misplaced×0.5) / tổng_từ_target × 100
      (từ thiếu = 0, tự bị phạt qua mẫu số)
    """
    target_seq = tokenize(target)
    trans_seq = tokenize(transcript)
    total = len(target_seq)
    if total == 0:
        return {"score": 100.0, "correct": 0, "misplaced": 0, "missing": 0}

    correct = misplaced = missing = 0
    last_pos = -1
    for word in target_seq:
        pos = trans_seq.index(word) if word in trans_seq else None
        if pos is None:
            missing += 1
        elif last_pos == -1 or pos > last_pos:
            correct += 1
            last_pos = pos
        else:
            misplaced += 1

    score = (correct * ORDER_CORRECT_WEIGHT +
             misplaced * ORDER_MISPLACED_WEIGHT) / total * 100
    return {"score": round(score, 2), "correct": correct,
            "misplaced": misplaced, "missing": missing}


def fluency_score(actual_duration: float, expected_duration: float) -> float:
    """
    INPUT : actual_duration (giây, từ audio bệnh nhân), expected_duration (giây, từ TTS bài đó).
    OUTPUT: 0-100. Đo tốc độ nói có hợp lý không.
    DÙNG Ở: NAM, CMD repetition, SEN.

    ratio = min/max  (đối xứng: nói nhanh gấp đôi và chậm gấp đôi đều bị phạt như nhau)
    ratio >= 0.5 -> fluency = ratio×100 ; ngược lại -> 0.
    Thiếu dữ liệu -> trả FLUENCY_FALLBACK (không phạt oan).
    """
    if not expected_duration or not actual_duration or expected_duration <= 0 or actual_duration <= 0:
        return FLUENCY_FALLBACK
    ratio = min(actual_duration, expected_duration) / max(actual_duration, expected_duration)
    return round(ratio * 100, 2) if ratio >= FLUENCY_MIN_RATIO else 0.0


# ==============================================================================
# BLOCK 4 — SUB-SCORERS  (1 hàm / 1 loại bài)
# ==============================================================================

def score_naming(ex: Exercise, transcript: str, audio_duration: float) -> dict:
    """
    NAM — Nhìn ảnh -> nói tên.
    Công thức: 0.50·keyword + 0.25·similarity + 0.15·fluency + 0.10·classifier
    OUTPUT: dict { "score", "components" }
    """
    kw = keyword_match(transcript, ex.accepted_answers)
    sim = text_similarity(transcript, ex.canonical_word)
    flu = fluency_score(audio_duration, ex.duration_expected)
    cls = classifier_present(transcript, ex.accepted_classifiers)

    score = (W_NAM["keyword"] * kw + W_NAM["similarity"] * sim +
             W_NAM["fluency"] * flu + W_NAM["classifier"] * cls)
    return {
        "score": round(score, 2),
        "components": {"keyword": kw, "text_similarity": sim,
                       "classifier_present": cls, "fluency": flu},
    }


def score_cmd_repetition(ex: Exercise, transcript: str, audio_duration: float) -> dict:
    """
    CMD Mode 2 — Nghe mô tả + nhìn ảnh -> nói tên (đã có 2 cue).
    Công thức: 0.40·keyword + 0.30·similarity + 0.20·classifier + 0.10·fluency
    (keyword nhẹ hơn NAM vì đã nghe đáp án; similarity+classifier nặng hơn để
     đánh vào độ hoàn thiện của đáp án sau khi được hỗ trợ.)
    OUTPUT: dict { "score", "components" }
    """
    kw = keyword_match(transcript, ex.accepted_answers)
    sim = text_similarity(transcript, ex.canonical_word)
    cls = classifier_present(transcript, ex.accepted_classifiers)
    flu = fluency_score(audio_duration, ex.duration_expected)

    score = (W_CMD2["keyword"] * kw + W_CMD2["similarity"] * sim +
             W_CMD2["classifier"] * cls + W_CMD2["fluency"] * flu)
    return {
        "score": round(score, 2),
        "components": {"keyword": kw, "text_similarity": sim,
                       "classifier_present": cls, "fluency": flu},
    }


def score_sentence(ex: Exercise, transcript: str, audio_duration: float,
                   attempt_number: int = 1) -> dict:
    """
    SEN — Nhìn câu khuyết + ảnh -> nói đủ câu.
    Công thức (attempt 1): 0.40·keyword + 0.50·order + 0.10·fluency
    Sau đó nhân attempt_multiplier (attempt 2 sau khi nghe audio mẫu = ×0.75, ...).
    OUTPUT: dict { "score" (đã nhân multiplier), "raw_score" (chưa nhân), "components", "used_fallback" }
    """
    kw = keyword_coverage(transcript, ex.missing_words)
    od = order_score(transcript, ex.full_sentence)
    flu = fluency_score(audio_duration, ex.duration_expected)

    raw = (W_SEN["keyword"] * kw + W_SEN["order"] * od["score"] +
           W_SEN["fluency"] * flu)
    multiplier = ATTEMPT_MULTIPLIER.get(attempt_number, 0.60)
    adjusted = raw * multiplier

    return {
        "score": round(adjusted, 2),
        "raw_score": round(raw, 2),
        "used_fallback": attempt_number > 1,
        "components": {
            "keyword": kw,
            "order_score": od["score"],
            "order_detail": {"correct": od["correct"],          # cho SLP dashboard
                             "misplaced": od["misplaced"],
                             "missing": od["missing"]},
            "fluency": flu,
        },
    }


def evaluate_cmd_recognition(ex: Exercise, selected_vocab_id: str) -> dict:
    """
    CMD Mode 1 — Nghe mô tả -> chọn đáp án bằng touch (KHÔNG dùng ASR, KHÔNG tính điểm).
    INPUT : selected_vocab_id (id bệnh nhân tap, từ Frontend).
    OUTPUT: dict { "is_correct": bool } -> chỉ Correct/Incorrect.
    DÙNG TIẾP: progression coi Correct như 1 bài đúng; Incorrect reset streak.
    """
    is_correct = (selected_vocab_id == ex.target_vocab_id)
    return {"is_correct": is_correct,
            "result": "correct" if is_correct else "incorrect"}


# ==============================================================================
# BLOCK 5 — ROUTER  (điểm vào duy nhất, gọi đúng sub-scorer)
# ==============================================================================

def score(ex: Exercise,
          transcript: str = "",
          audio_duration: float = 0.0,
          asr_confidence: float = 1.0,
          selected_vocab_id: str = "",
          attempt_number: int = 1) -> ScoreResult:
    """
    HÀM CHÍNH — Backend gọi hàm này cho mỗi lượt làm bài.

    INPUT lấy từ đâu:
      - ex                : Backend load từ DB (Exercise_bank + Asset)
      - transcript        : ASR module (PhoWhisper)        [bài speech]
      - audio_duration    : Audio Input module             [bài speech]
      - asr_confidence    : ASR module                     [bài speech]
      - selected_vocab_id : Frontend (touch)               [CMD recognition]
      - attempt_number    : Rule Engine đếm lần thử        [SEN fallback]

    OUTPUT: ScoreResult (đầy đủ, sẵn sàng lưu DB + trả Frontend).
    """
    base = dict(exercise_id=ex.exercise_id, exercise_type=ex.exercise_type,
                mode=ex.mode, vocab_level=ex.vocab_level, topic=ex.topic,
                transcript=normalize_text(transcript) or None,
                selected_vocab_id=selected_vocab_id or None,
                audio_duration_s=audio_duration or None,
                asr_confidence=asr_confidence,
                attempt_number=attempt_number)

    # --- CMD recognition: touch, không ASR, không gate, không điểm ---
    if ex.exercise_type == "command_identification" and ex.mode == "recognition":
        out = evaluate_cmd_recognition(ex, selected_vocab_id)
        return ScoreResult(
            score=None, raw_score=None, weighted_score=None,
            is_correct=out["is_correct"], components={"binary_touch": out["is_correct"]},
            result=out["result"], used_fallback_audio=False, **base)

    # --- Bài speech: chạy input gate trước ---
    err = is_invalid_input(transcript, audio_duration, asr_confidence)
    if err:
        return ScoreResult(
            score=None, raw_score=None, weighted_score=None, is_correct=None,
            components={"error": err}, result="invalid",
            used_fallback_audio=False, **base)

    # --- Route theo loại bài ---
    if ex.exercise_type == "naming":
        out = score_naming(ex, transcript, audio_duration)
        raw = adjusted = out["score"]
        used_fallback = False
    elif ex.exercise_type == "command_identification" and ex.mode == "repetition":
        out = score_cmd_repetition(ex, transcript, audio_duration)
        raw = adjusted = out["score"]
        used_fallback = False
    elif ex.exercise_type == "sentence_building":
        out = score_sentence(ex, transcript, audio_duration, attempt_number)
        raw = out["raw_score"]
        adjusted = out["score"]
        used_fallback = out["used_fallback"]
    else:
        raise ValueError(f"Loại bài không hỗ trợ: {ex.exercise_type} / mode={ex.mode}")

    weighted = apply_difficulty_weight(raw, ex.vocab_level)   # BLOCK 8

    return ScoreResult(
        score=adjusted, raw_score=raw, weighted_score=weighted, is_correct=None,
        components=out["components"], result=classify(adjusted),   # BLOCK 6
        used_fallback_audio=used_fallback, **base)


# ==============================================================================
# BLOCK 6 — CLASSIFY  (score -> pass / near / retry)
# ==============================================================================

def classify(score_value: float) -> str:
    """
    INPUT : score 0-100 (chỉ bài có điểm; CMD recognition đã trả correct/incorrect riêng).
    OUTPUT: "pass" | "near" | "retry".
    DÙNG TIẾP:
      - pass  -> chuyển bài, cộng correct_streak
      - near  -> phát TTS 0.75×, cho thử lại (tối đa 3), reset correct_streak
      - retry -> phát TTS 0.6×, hết 3 lần -> skip, reset correct_streak
    """
    if score_value >= PASS_THRESHOLD:
        return "pass"
    if score_value >= NEAR_THRESHOLD:
        return "near"
    return "retry"


# ==============================================================================
# BLOCK 7 — PROGRESSION  (vocab level TRONG SESSION)
# ==============================================================================

@dataclass
class ProgressionState:
    """
    Trạng thái progression của 1 session. Backend giữ object này trong suốt buổi,
    RESET về mặc định khi bắt đầu session mới (làm xong 10 bài).
    """
    vocab_level: int = MIN_VOCAB_LEVEL
    correct_streak: int = 0          # số bài đúng liên tiếp CÙNG topic
    current_topic: Optional[str] = None


def _is_correct_for_progression(result: str) -> bool:
    """Quy ước 'đúng' để tính streak: PASS (speech) hoặc Correct (CMD recognition)."""
    return result in ("pass", "correct")


def update_vocab_level(state: ProgressionState, result: str, topic: str) -> dict:
    """
    INPUT : state hiện tại, result của bài vừa chấm, topic của bài.
    OUTPUT: dict { "action": "level_up"|"hold", "vocab_level", "correct_streak" }
            và CẬP NHẬT state tại chỗ.
    DÙNG TIẾP: vocab_level mới được dùng để chọn độ khó từ vựng cho bài kế tiếp
               TRONG session. Hết session -> gọi reset_session().

    LOGIC: cứ 3 bài đúng liên tiếp cùng topic -> +1 level (tối đa 3).
           Đổi topic, hoặc bài sai/near -> reset streak.
           Không phân biệt loại bài (CMD recognition Correct cũng tính).
    """
    # đổi topic -> chuỗi đứt
    if state.current_topic is not None and topic != state.current_topic:
        state.correct_streak = 0
    state.current_topic = topic

    if _is_correct_for_progression(result):
        state.correct_streak += 1
    else:
        state.correct_streak = 0

    if (state.correct_streak >= CORRECT_STREAK_TO_LEVEL_UP
            and state.vocab_level < MAX_VOCAB_LEVEL):
        state.vocab_level += 1
        state.correct_streak = 0          # reset sau khi lên level
        return {"action": "level_up", "vocab_level": state.vocab_level,
                "correct_streak": state.correct_streak}

    return {"action": "hold", "vocab_level": state.vocab_level,
            "correct_streak": state.correct_streak}


def reset_session(state: ProgressionState) -> None:
    """Gọi khi bắt đầu session mới: vocab level về 1, xóa streak."""
    state.vocab_level = MIN_VOCAB_LEVEL
    state.correct_streak = 0
    state.current_topic = None


# ==============================================================================
# BLOCK 8 — DIFFICULTY WEIGHTING  (điểm cho SLP dashboard)
# ==============================================================================

def apply_difficulty_weight(raw_score: Optional[float], vocab_level: int) -> Optional[float]:
    """
    INPUT : raw_score (0-100), vocab_level (1-3) tại thời điểm làm bài.
    OUTPUT: weighted_score = raw × multiplier (level 1=1.0, 2=1.15, 3=1.30). Có thể >100.
    DÙNG Ở: CHỈ SLP dashboard, để thể hiện tiến bộ thực chất (đúng ở level khó đáng giá hơn).
            KHÔNG ảnh hưởng raw_score, KHÔNG ảnh hưởng progression.
    """
    if raw_score is None:
        return None
    return round(raw_score * DIFFICULTY_MULTIPLIER.get(vocab_level, 1.0), 2)


# ==============================================================================
# ==============================================================================
#  TEST SUITE
# ==============================================================================
# ==============================================================================
# Chạy: python phucngon_scoring.py   (tự chạy, in PASS/FAIL)
#       pytest phucngon_scoring.py   (nếu có pytest)
#
# Quy ước assert:
#   - Thành phần tất định (keyword, classifier, order, fluency) -> assert CHÍNH XÁC.
#   - Tổng điểm phụ thuộc similarity -> assert kết quả phân loại (pass/near/retry)
#     và khoảng điểm, tránh brittle do làm tròn.
# ==============================================================================

def _approx(a: float, b: float, tol: float = 0.5) -> bool:
    return abs(a - b) <= tol


# --- Fixtures: dữ liệu mẫu giống Asset.xlsx ----------------------------------

def _ex_naming():
    return Exercise(
        exercise_id="NAM001", exercise_type="naming", topic="đồ vật quen thuộc",
        vocab_level=1, canonical_word="cái kéo",
        accepted_answers=["kéo", "cây kéo", "cái kéo"],
        accepted_classifiers=["cái", "cây"], duration_expected=2.0)


def _ex_cmd2():
    return Exercise(
        exercise_id="CMD002", exercise_type="command_identification",
        mode="repetition", topic="đồ vật quen thuộc", vocab_level=1,
        canonical_word="cái kéo", accepted_answers=["kéo", "cây kéo", "cái kéo"],
        accepted_classifiers=["cái", "cây"], duration_expected=2.0)


def _ex_cmd1():
    return Exercise(
        exercise_id="CMD001", exercise_type="command_identification",
        mode="recognition", topic="đồ vật quen thuộc", vocab_level=1,
        target_vocab_id="V001", distractor_vocab_ids=["V002", "V003", "V004"])


def _ex_sen():
    return Exercise(
        exercise_id="SEN001", exercise_type="sentence_building",
        topic="hoạt động thường ngày", vocab_level=1,
        full_sentence="tôi đang ăn cơm", missing_words=["ăn", "cơm"],
        duration_expected=2.0)


# --- BLOCK 1: normalize ------------------------------------------------------

def test_normalize_basic():
    assert normalize_text("Cái Kéo!") == "cái kéo"
    assert normalize_text("  tôi   ăn  cơm  ") == "tôi ăn cơm"
    assert normalize_text("UỐNG NƯỚC.") == "uống nước"
    assert normalize_text("") == ""


def test_normalize_unicode_nfc():
    # "à" dạng tổ hợp (a + U+0300) phải bằng dạng precomposed
    decomposed = "a\u0300n"      # a + huyền + n  = "àn"
    precomposed = "àn"
    assert normalize_text(decomposed) == normalize_text(precomposed)


# --- BLOCK 3: component scorers ----------------------------------------------

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


def test_classifier_present_bugfix():
    cls = ["cái", "cây"]
    assert classifier_present("cái kéo", cls) == 100.0
    assert classifier_present("cây kéo", cls) == 100.0
    assert classifier_present("kéo", cls) == 0.0          # thiếu loại từ
    assert classifier_present("tờ kéo", cls) == 0.0       # BUG FIX: "tờ" sai -> KHÔNG còn 100
    assert classifier_present("kéo", []) == 100.0          # vocab không cần loại từ


def test_order_score_values():
    t = "tôi đang ăn cơm"
    assert order_score("tôi đang ăn cơm", t)["score"] == 100.0
    assert order_score("tôi đang cơm ăn", t)["score"] == 87.5
    assert order_score("tôi ăn cơm", t)["score"] == 75.0
    assert order_score("cơm ăn đang tôi", t)["score"] == 62.5
    assert order_score("tôi cơm ăn", t)["score"] == 62.5
    assert order_score("ăn cơm", t)["score"] == 50.0
    assert order_score("đi học", t)["score"] == 0.0


def test_order_score_detail():
    d = order_score("tôi cơm ăn", "tôi đang ăn cơm")
    assert (d["correct"], d["misplaced"], d["missing"]) == (2, 1, 1)


def test_fluency():
    assert fluency_score(2.0, 2.0) == 100.0
    assert _approx(fluency_score(2.6, 2.0), 76.92, 0.5)
    assert fluency_score(5.0, 2.0) == 0.0      # chậm > gấp đôi -> 0
    assert fluency_score(0.8, 2.0) == 0.0      # nhanh > gấp đôi -> 0
    assert fluency_score(0, 2.0) == FLUENCY_FALLBACK


# --- BLOCK 4 + 5: sub-scorers qua router -------------------------------------

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
    # thiếu 1 từ khuyết -> keyword 50, order 75 -> 0.4*50+0.5*75+0.1*flu
    r = score(_ex_sen(), transcript="tôi đang ăn", audio_duration=2.0, asr_confidence=0.9)
    assert r.components["keyword"] == 50.0
    assert r.components["order_score"] == 75.0
    # 20 + 37.5 + 10 = 67.5 -> near
    assert r.result == "near"


def test_sentence_wrong_action_retry():
    r = score(_ex_sen(), transcript="tôi đang đi học", audio_duration=2.0, asr_confidence=0.9)
    assert r.components["keyword"] == 0.0
    assert r.result == "retry"


def test_sentence_fallback_multiplier():
    # cùng transcript đúng, attempt 2 (sau khi nghe audio mẫu) phải thấp hơn attempt 1
    a1 = score(_ex_sen(), transcript="tôi đang ăn cơm", audio_duration=2.0,
               asr_confidence=0.9, attempt_number=1)
    a2 = score(_ex_sen(), transcript="tôi đang ăn cơm", audio_duration=2.0,
               asr_confidence=0.9, attempt_number=2)
    assert a2.score < a1.score
    assert _approx(a2.score, a1.raw_score * 0.75, 0.5)
    assert a2.used_fallback_audio is True


# --- BLOCK 2: input gate -----------------------------------------------------

def test_input_gate():
    ex = _ex_naming()
    assert score(ex, transcript="cái kéo", audio_duration=0.2, asr_confidence=0.9).result == "invalid"
    assert score(ex, transcript="", audio_duration=2.0, asr_confidence=0.9).result == "invalid"
    assert score(ex, transcript="cái kéo", audio_duration=2.0, asr_confidence=0.2).result == "invalid"


# --- BLOCK 8: difficulty weighting -------------------------------------------

def test_difficulty_weight():
    assert apply_difficulty_weight(75, 1) == 75.0
    assert apply_difficulty_weight(75, 2) == 86.25
    assert apply_difficulty_weight(75, 3) == 97.5
    assert apply_difficulty_weight(None, 3) is None


# --- BLOCK 7: progression (in-session) ---------------------------------------

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


# ==============================================================================
#  TEST RUNNER (chạy không cần pytest)
# ==============================================================================

def _run_all_tests():
    import sys
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    passed = failed = 0
    print("=" * 70)
    print(f" PhụcNgôn Scoring Engine — chạy {len(tests)} test")
    print("=" * 70)
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {name}  -- FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ {name}  -- ERROR: {type(e).__name__}: {e}")
            failed += 1
    print("=" * 70)
    print(f"  KẾT QUẢ: {passed} passed, {failed} failed")
    print("=" * 70)

    # Demo: in 1 ScoreResult JSON mẫu để team thấy output
    print("\n--- VÍ DỤ OUTPUT (SEN, nói thiếu 'đang') ---")
    import json
    demo = score(_ex_sen(), transcript="tôi ăn cơm", audio_duration=2.4, asr_confidence=0.9)
    print(json.dumps(demo.to_dict(), ensure_ascii=False, indent=2))

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    _run_all_tests()
