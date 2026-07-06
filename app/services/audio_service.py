"""
================================================================================
 PhụcNgôn — AUDIO PIPELINE  (MVP Phase 1)
================================================================================
 Owner: Hào  |  Module 1 (Audio Capture) + Module 6 (Feedback UI)

 Nguồn: chuyển thể từ phucngon_audio.py (tác giả: Hào, Module 1 - Audio Capture),
 giữ nguyên logic xử lý, chỉ đổi vị trí vào service layer.

 File này hiện thực toàn bộ pipeline xử lý audio phía server:
   nhận file WAV từ Frontend (Expo) → validate → tính VAD/duration/RMS
   → trả AudioInfo cho ASR module (Vy) + Scoring module (Nam).

 DÙNG Ở ĐÂU: app/services/audio_service.py là tầng service xử lý audio.
   Backend gọi process_audio(wav_bytes) để nhận AudioInfo, sau đó:
   - Gửi trimmed_wav_bytes cho ASR (Vy)
   - Gửi speech_duration_s cho Scoring (Nam)

 ==============================================================================

 SƠ ĐỒ LUỒNG DỮ LIỆU (đọc từ trên xuống):

   [Hào — Expo gửi lên]
        file WAV (bytes)  |  filename  |  content_type
              │
              ▼
   ┌─────────────────────────────────────────────────────────┐
   │ BLOCK 1: validate_wav_format()                           │
   │   check sample_rate=16000 / channels=1 / sampwidth=2     │
   │   → nếu sai spec -> WavFormatError (không chấm)          │
   └─────────────────────────────────────────────────────────┘
              │
              ▼
   ┌─────────────────────────────────────────────────────────┐
   │ BLOCK 2: extract_audio_info()                            │
   │   tính duration_s, rms_db, peak_db từ PCM samples        │
   └─────────────────────────────────────────────────────────┘
              │
              ▼
   ┌─────────────────────────────────────────────────────────┐
   │ BLOCK 3: detect_speech_boundaries()  (VAD đơn giản)      │
   │   tìm frame có giọng nói → speech_start_s, speech_end_s  │
   │   → tính speech_duration_s (loại bỏ khoảng lặng đầu/cuối)│
   └─────────────────────────────────────────────────────────┘
              │
              ▼
   ┌─────────────────────────────────────────────────────────┐
   │ BLOCK 4: validate_speech_content()                       │
   │   audio quá ngắn / quá im lặng -> REJECT                 │
   └─────────────────────────────────────────────────────────┘
              │ (hợp lệ)
              ▼
   ┌─────────────────────────────────────────────────────────┐
   │ BLOCK 5: trim_silence()                                  │
   │   cắt khoảng lặng đầu/cuối → bytes WAV sạch cho ASR     │
   └─────────────────────────────────────────────────────────┘
              │
              ▼
        AudioInfo (dataclass) -> trả cho Tuấn Anh (Backend)
        Tuấn Anh chuyển tiếp audio_bytes cho Vy (ASR)
        và audio_duration_s cho Nam (Scoring → fluency_score)
"""

from __future__ import annotations

import io
import math
import struct
import wave
from dataclasses import dataclass, asdict
from typing import Optional


# ==============================================================================
# CONSTANTS — Các ngưỡng & spec đã chốt
# ==============================================================================
# Mọi con số "ma thuật" gom về đây để team chỉnh 1 chỗ, không rải khắp code.

# --- Spec WAV bắt buộc (BLOCK 1) ---
REQUIRED_SAMPLE_RATE  = 16000   # Hz — Whisper/PhoWhisper yêu cầu
REQUIRED_CHANNELS     = 1       # mono
REQUIRED_SAMPLE_WIDTH = 2       # bytes = 16-bit PCM

# --- Input gate (BLOCK 4) ---
MIN_SPEECH_DURATION_S = 0.3     # giây — ngắn hơn coi như không nói
MAX_AUDIO_DURATION_S  = 15.0    # giây — dài hơn coi là lỗi (VAD nên đã dừng trước)
MIN_RMS_DB            = -50.0   # dB — im hơn coi là không có giọng

# --- VAD (BLOCK 3) ---
VAD_FRAME_MS          = 20      # ms mỗi frame để phân tích VAD
VAD_SILENCE_THRESHOLD = -40.0   # dB — frame dưới ngưỡng này coi là im lặng
VAD_MIN_SPEECH_FRAMES = 3       # cần ít nhất N frame liên tiếp có tiếng mới tính là speech

# --- Trim silence (BLOCK 5) ---
TRIM_PADDING_MS       = 100     # ms padding giữ lại ở đầu/cuối sau khi trim


# ==============================================================================
# EXCEPTIONS — Lỗi có ý nghĩa rõ ràng, không dùng Exception chung
# ==============================================================================

class WavFormatError(ValueError):
    """
    Raise khi file WAV không đúng spec (sai sample_rate / channels / bit depth).
    Backend (Tuấn Anh) bắt lỗi này và trả HTTP 422 cho Frontend.
    """
    pass


class AudioContentError(ValueError):
    """
    Raise khi format WAV đúng nhưng nội dung không hợp lệ:
    quá ngắn, quá im lặng, hoặc quá dài (VAD lỗi phía client).
    Backend trả HTTP 422 kèm error_code để Frontend hiển thị đúng message.
    """
    def __init__(self, error_code: str, message: str):
        self.error_code = error_code   # "TOO_SHORT" | "TOO_QUIET" | "TOO_LONG"
        super().__init__(message)


# ==============================================================================
# DATA MODELS — Cấu trúc dữ liệu vào/ra
# ==============================================================================

@dataclass
class AudioInfo:
    """
    MÔ TẢ: Kết quả sau khi xử lý audio. Đây là object trả về cho Backend (Tuấn Anh).
           Tuấn Anh dùng:
             - trimmed_wav_bytes  -> gửi cho Vy (ASR) để nhận transcript
             - speech_duration_s  -> gửi cho Nam (Scoring) để tính fluency_score
             - rms_db, peak_db    -> lưu DB để SLP phân tích sau

    DÙNG Ở ĐÂU: output duy nhất của process_audio().

    GHI CHÚ:
      - trimmed_wav_bytes là file WAV hoàn chỉnh (có header), không phải raw PCM.
      - speech_duration_s là thời gian có giọng nói thực sự (đã loại khoảng lặng).
      - total_duration_s là tổng thời gian file gốc (kể cả khoảng lặng đầu/cuối).
    """
    # Thông tin file gốc
    total_duration_s:    float          # tổng thời gian file WAV gốc
    sample_rate:         int            # luôn là 16000 nếu qua validate
    channels:            int            # luôn là 1 (mono)
    sample_width:        int            # luôn là 2 (16-bit)

    # Thông tin giọng nói
    speech_start_s:      float          # giây bắt đầu có giọng nói
    speech_end_s:        float          # giây kết thúc giọng nói
    speech_duration_s:   float          # = speech_end_s - speech_start_s
    rms_db:              float          # RMS của toàn file (dB) — đo độ to tổng thể
    peak_db:             float          # peak của toàn file (dB) — đo tiếng to nhất

    # Bytes WAV đã trim (gửi cho ASR)
    trimmed_wav_bytes:   bytes          # WAV header + PCM samples đã cắt lặng

    def to_dict(self) -> dict:
        """Trả về dict để serialize JSON — bỏ trimmed_wav_bytes (binary)."""
        d = asdict(self)
        d.pop("trimmed_wav_bytes")
        d["trimmed_wav_size_bytes"] = len(self.trimmed_wav_bytes)
        return d


# ==============================================================================
# BLOCK 1 — VALIDATE WAV FORMAT
# ==============================================================================

def validate_wav_format(wav_bytes: bytes) -> wave.Wave_read:
    """
    INPUT : raw bytes của file WAV (từ multipart/form-data request).
    OUTPUT: wave.Wave_read object đã mở, sẵn sàng đọc samples.
    RAISE : WavFormatError nếu không phải WAV hoặc sai spec.

    DÙNG TIẾP: extract_audio_info() và detect_speech_boundaries() nhận object này.

    Spec bắt buộc (chốt trong Audio Pipeline Spec Doc):
      - sample_rate  = 16,000 Hz  (Whisper yêu cầu)
      - channels     = 1          (mono — stereo tốn gấp đôi bandwidth vô ích)
      - sample_width = 2 bytes    (16-bit PCM — định dạng thô, không nén)
    """
    try:
        wav_file = wave.open(io.BytesIO(wav_bytes), "rb")
    except wave.Error as e:
        raise WavFormatError(f"Không phải file WAV hợp lệ: {e}")
    except EOFError:
        raise WavFormatError("File WAV rỗng hoặc bị cắt ngắn")

    sr  = wav_file.getframerate()
    ch  = wav_file.getnchannels()
    sw  = wav_file.getsampwidth()

    errors = []
    if sr != REQUIRED_SAMPLE_RATE:
        errors.append(
            f"sample_rate={sr}Hz (cần {REQUIRED_SAMPLE_RATE}Hz — "
            f"Expo ghi sai preset, kiểm tra WHISPER_PRESET.sampleRate)"
        )
    if ch != REQUIRED_CHANNELS:
        errors.append(
            f"channels={ch} (cần {REQUIRED_CHANNELS} — mono, "
            f"kiểm tra WHISPER_PRESET.numberOfChannels)"
        )
    if sw != REQUIRED_SAMPLE_WIDTH:
        errors.append(
            f"sample_width={sw * 8}bit (cần {REQUIRED_SAMPLE_WIDTH * 8}bit PCM)"
        )

    if errors:
        wav_file.close()
        raise WavFormatError("WAV sai spec:\n  - " + "\n  - ".join(errors))

    return wav_file


# ==============================================================================
# BLOCK 2 — EXTRACT AUDIO INFO (duration, RMS, peak)
# ==============================================================================

def _samples_to_rms_db(samples: list[int]) -> float:
    """
    INPUT : list[int] — PCM 16-bit samples (range -32768..32767).
    OUTPUT: RMS tính theo dB. Trả -inf nếu không có sample.

    DÙNG TIẾP: extract_audio_info(), _frame_rms_db() cho VAD.

    Công thức:
      RMS  = sqrt(mean(x²))
      dBFS = 20 * log10(RMS / 32768)   (32768 = full scale 16-bit)
    """
    if not samples:
        return -math.inf
    mean_sq = sum(s * s for s in samples) / len(samples)
    rms = math.sqrt(mean_sq)
    if rms == 0:
        return -math.inf
    return round(20 * math.log10(rms / 32768), 2)


def _read_samples(wav_file: wave.Wave_read) -> list[int]:
    """
    INPUT : wave.Wave_read đã mở ở bất kỳ vị trí nào.
    OUTPUT: list[int] toàn bộ PCM samples (16-bit signed).

    DÙNG TIẾP: extract_audio_info(), detect_speech_boundaries().
    """
    wav_file.rewind()
    raw = wav_file.readframes(wav_file.getnframes())
    # "<h" = little-endian signed short (16-bit) — đúng với PCM 16-bit WAV
    return list(struct.unpack(f"<{len(raw) // 2}h", raw))


def extract_audio_info(wav_file: wave.Wave_read) -> tuple[float, float, float]:
    """
    INPUT : wave.Wave_read (đã validate format ở BLOCK 1).
    OUTPUT: tuple (total_duration_s, rms_db, peak_db).
    DÙNG TIẾP: process_audio() điền vào AudioInfo.

    peak_db: sample tuyệt đối lớn nhất, dùng để phát hiện clipping.
    """
    sr        = wav_file.getframerate()
    n_frames  = wav_file.getnframes()
    total_dur = round(n_frames / sr, 4)

    samples   = _read_samples(wav_file)
    rms_db    = _samples_to_rms_db(samples)

    if samples:
        peak = max(abs(s) for s in samples)
        peak_db = round(20 * math.log10(peak / 32768), 2) if peak > 0 else -math.inf
    else:
        peak_db = -math.inf

    return total_dur, rms_db, peak_db


# ==============================================================================
# BLOCK 3 — VAD: DETECT SPEECH BOUNDARIES
# ==============================================================================

def _frame_rms_db(samples: list[int], start: int, end: int) -> float:
    """
    INPUT : toàn bộ samples, chỉ số start/end của frame cần tính.
    OUTPUT: RMS (dB) của frame đó.
    DÙNG TIẾP: detect_speech_boundaries() gọi cho từng frame.
    """
    frame = samples[start:end]
    return _samples_to_rms_db(frame)


def detect_speech_boundaries(wav_file: wave.Wave_read) -> tuple[float, float]:
    """
    INPUT : wave.Wave_read (đã validate).
    OUTPUT: tuple (speech_start_s, speech_end_s).
            Nếu không tìm thấy tiếng nói -> trả (0.0, 0.0).
    DÙNG TIẾP: process_audio() dùng để trim và tính speech_duration_s.

    THUẬT TOÁN (VAD đơn giản, không cần thư viện):
      1. Chia audio thành các frame VAD_FRAME_MS ms.
      2. Tính RMS (dB) từng frame.
      3. Frame có RMS > VAD_SILENCE_THRESHOLD là "có tiếng".
      4. speech_start = frame đầu tiên có ít nhất VAD_MIN_SPEECH_FRAMES frame
         liên tiếp "có tiếng" (tránh nhầm tiếng click ngắn).
      5. speech_end = frame cuối cùng có tiếng.

    [SWAP] PRODUCTION: thay bằng webrtcvad.Vad(mode=2) cho VAD cấp frame
           chính xác hơn, đặc biệt với giọng thều thào (bệnh nhân nặng).
    """
    sr      = wav_file.getframerate()
    samples = _read_samples(wav_file)

    frame_size  = int(sr * VAD_FRAME_MS / 1000)   # số samples/frame
    n_frames    = len(samples) // frame_size

    if n_frames == 0:
        return 0.0, 0.0

    # Đánh dấu từng frame: True = có tiếng
    is_speech = []
    for i in range(n_frames):
        db = _frame_rms_db(samples, i * frame_size, (i + 1) * frame_size)
        is_speech.append(db > VAD_SILENCE_THRESHOLD)

    # Tìm speech_start: frame đầu tiên trong run "có tiếng" >= VAD_MIN_SPEECH_FRAMES
    speech_start_frame = None
    for i in range(n_frames - VAD_MIN_SPEECH_FRAMES + 1):
        if all(is_speech[i:i + VAD_MIN_SPEECH_FRAMES]):
            speech_start_frame = i
            break

    if speech_start_frame is None:
        return 0.0, 0.0   # không tìm thấy tiếng nói

    # Tìm speech_end: frame có tiếng cuối cùng
    speech_end_frame = speech_start_frame
    for i in range(n_frames - 1, speech_start_frame - 1, -1):
        if is_speech[i]:
            speech_end_frame = i
            break

    speech_start_s = round(speech_start_frame * VAD_FRAME_MS / 1000, 4)
    speech_end_s   = round((speech_end_frame + 1) * VAD_FRAME_MS / 1000, 4)
    return speech_start_s, speech_end_s


# ==============================================================================
# BLOCK 4 — VALIDATE SPEECH CONTENT
# ==============================================================================

def validate_speech_content(total_duration_s: float,
                             speech_duration_s: float,
                             rms_db: float) -> Optional[str]:
    """
    INPUT : kết quả từ BLOCK 2 và BLOCK 3.
    OUTPUT: None nếu hợp lệ; ngược lại trả ERROR_CODE (str).
    RAISE : AudioContentError với error_code và message tiếng Việt.
    DÙNG TIẾP: process_audio() gọi sau khi có đủ thông tin.

    ERROR_CODE    Frontend hiển thị
    -----------   ------------------------------------------
    TOO_SHORT     "Hãy nói to và đủ câu nhé!"
    TOO_QUIET     "Micro chưa nghe rõ, nói to hơn một chút!"
    TOO_LONG      "Bản ghi âm quá dài, thử nói ngắn lại nhé!"
    """
    if speech_duration_s < MIN_SPEECH_DURATION_S:
        raise AudioContentError(
            "TOO_SHORT",
            f"Giọng nói quá ngắn ({speech_duration_s:.2f}s < {MIN_SPEECH_DURATION_S}s)"
        )
    if rms_db < MIN_RMS_DB:
        raise AudioContentError(
            "TOO_QUIET",
            f"Âm lượng quá thấp ({rms_db:.1f}dB < {MIN_RMS_DB}dB)"
        )
    if total_duration_s > MAX_AUDIO_DURATION_S:
        raise AudioContentError(
            "TOO_LONG",
            f"File quá dài ({total_duration_s:.1f}s > {MAX_AUDIO_DURATION_S}s) "
            f"— VAD phía client có thể bị lỗi"
        )
    return None


# ==============================================================================
# BLOCK 5 — TRIM SILENCE
# ==============================================================================

def trim_silence(wav_file: wave.Wave_read,
                 speech_start_s: float,
                 speech_end_s: float) -> bytes:
    """
    INPUT : wav_file, speech_start_s và speech_end_s từ BLOCK 3.
    OUTPUT: bytes của file WAV đã cắt khoảng lặng (có header đầy đủ).
            ASR (Vy) nhận bytes này thay vì file gốc.
    DÙNG TIẾP: process_audio() trả kết quả trong AudioInfo.trimmed_wav_bytes.

    Giữ lại TRIM_PADDING_MS ms ở đầu/cuối để tránh cắt mất âm tiết đầu/cuối.
    Nếu speech_start/end không xác định được (=0,0) -> trả nguyên file gốc.
    """
    sr = wav_file.getframerate()
    sw = wav_file.getsampwidth()
    ch = wav_file.getnchannels()

    samples   = _read_samples(wav_file)
    n_samples = len(samples)

    padding_samples = int(sr * TRIM_PADDING_MS / 1000)

    if speech_start_s == 0.0 and speech_end_s == 0.0:
        # Không detect được boundary -> trả file nguyên
        start_idx = 0
        end_idx   = n_samples
    else:
        start_idx = max(0, int(speech_start_s * sr) - padding_samples)
        end_idx   = min(n_samples, int(speech_end_s * sr) + padding_samples)

    trimmed_samples = samples[start_idx:end_idx]

    # Đóng gói lại thành file WAV hoàn chỉnh (có header)
    raw_bytes = struct.pack(f"<{len(trimmed_samples)}h", *trimmed_samples)
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(ch)
        wf.setsampwidth(sw)
        wf.setframerate(sr)
        wf.writeframes(raw_bytes)
    return out.getvalue()


# ==============================================================================
# BLOCK 6 — ROUTER: process_audio()  (hàm duy nhất Tuấn Anh gọi)
# ==============================================================================

def process_audio(wav_bytes: bytes) -> AudioInfo:
    """
    INPUT : raw bytes của file WAV từ multipart/form-data (Expo gửi lên).
    OUTPUT: AudioInfo — object chứa đủ thông tin cho ASR (Vy) và Scoring (Nam).
    RAISE : WavFormatError nếu file sai spec.
            AudioContentError nếu nội dung không hợp lệ.

    ĐÂY LÀ HÀM DUY NHẤT backend gọi. Toàn bộ BLOCK 1-5 được gọi bên trong.

    VÍ DỤ sử dụng trong FastAPI (Tuấn Anh):
    ─────────────────────────────────────────
        from app.services.audio_service import process_audio, WavFormatError, AudioContentError

        @app.post("/v1/session/submit")
        async def submit(audio: UploadFile = File(...)):
            wav_bytes = await audio.read()
            try:
                info = process_audio(wav_bytes)
            except WavFormatError as e:
                raise HTTPException(422, detail=str(e))
            except AudioContentError as e:
                raise HTTPException(422, detail={"error_code": e.error_code, "message": str(e)})

            transcript = await asr_module.transcribe(info.trimmed_wav_bytes)   # Vy
            result = scoring_module.score(..., audio_duration=info.speech_duration_s)  # Nam
            return result
    ─────────────────────────────────────────
    """
    # BLOCK 1 — validate format
    wav_file = validate_wav_format(wav_bytes)

    try:
        # BLOCK 2 — extract info
        total_duration_s, rms_db, peak_db = extract_audio_info(wav_file)

        # BLOCK 3 — VAD
        speech_start_s, speech_end_s = detect_speech_boundaries(wav_file)
        speech_duration_s = round(speech_end_s - speech_start_s, 4)

        # BLOCK 4 — validate content
        validate_speech_content(total_duration_s, speech_duration_s, rms_db)

        # BLOCK 5 — trim
        trimmed_wav_bytes = trim_silence(wav_file, speech_start_s, speech_end_s)

    finally:
        wav_file.close()

    return AudioInfo(
        total_duration_s  = total_duration_s,
        sample_rate       = REQUIRED_SAMPLE_RATE,
        channels          = REQUIRED_CHANNELS,
        sample_width      = REQUIRED_SAMPLE_WIDTH,
        speech_start_s    = speech_start_s,
        speech_end_s      = speech_end_s,
        speech_duration_s = speech_duration_s,
        rms_db            = rms_db,
        peak_db           = peak_db,
        trimmed_wav_bytes = trimmed_wav_bytes,
    )
