"""
Test suite cho app.services.audio_service

Gồm các test cho từng BLOCK của audio pipeline:
- BLOCK 1: validate_wav_format
- BLOCK 2: extract_audio_info
- BLOCK 3: detect_speech_boundaries
- BLOCK 4: validate_speech_content
- BLOCK 5: trim_silence
- BLOCK 6: process_audio (integration)
"""

import io
import math
import struct
import wave

import pytest

from app.services.audio_service import (
    REQUIRED_CHANNELS,
    REQUIRED_SAMPLE_RATE,
    REQUIRED_SAMPLE_WIDTH,
    AudioContentError,
    AudioInfo,
    WavFormatError,
    detect_speech_boundaries,
    extract_audio_info,
    process_audio,
    trim_silence,
    validate_speech_content,
    validate_wav_format,
)


# ==============================================================================
# HELPERS — tạo WAV giả để test (không cần file thật)
# ==============================================================================


def _make_wav(
    duration_s: float = 2.0,
    sample_rate: int = REQUIRED_SAMPLE_RATE,
    channels: int = REQUIRED_CHANNELS,
    sample_width: int = REQUIRED_SAMPLE_WIDTH,
    amplitude: int = 8000,
    silent_start_s: float = 0.3,
    silent_end_s: float = 0.3,
) -> bytes:
    """
    Tạo file WAV giả để test: [im lặng] + [sine wave] + [im lặng].
    amplitude=0 tạo file im lặng hoàn toàn.
    """
    n_total = int(duration_s * sample_rate)
    n_silence_start = int(silent_start_s * sample_rate)
    n_silence_end = int(silent_end_s * sample_rate)
    n_speech = n_total - n_silence_start - n_silence_end

    samples = (
        [0] * n_silence_start
        + [
            int(amplitude * math.sin(2 * math.pi * 200 * i / sample_rate))
            for i in range(max(0, n_speech))
        ]
        + [0] * n_silence_end
    )

    raw = struct.pack(f"<{len(samples)}h", *samples)
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(raw)
    return out.getvalue()


def _approx(a: float, b: float, tol: float = 0.05) -> bool:
    return abs(a - b) <= tol


# ==============================================================================
# TEST SUITE — BLOCK 1: validate_wav_format
# ==============================================================================


def test_valid_wav_passes():
    wav = _make_wav()
    wf = validate_wav_format(wav)
    assert wf.getframerate() == REQUIRED_SAMPLE_RATE
    assert wf.getnchannels() == REQUIRED_CHANNELS
    assert wf.getsampwidth() == REQUIRED_SAMPLE_WIDTH
    wf.close()


def test_wrong_sample_rate_raises():
    wav = _make_wav(sample_rate=44100)
    with pytest.raises(WavFormatError) as exc_info:
        validate_wav_format(wav)
    assert "44100" in str(exc_info.value)


def test_stereo_raises():
    wav = _make_wav(channels=2)
    with pytest.raises(WavFormatError) as exc_info:
        validate_wav_format(wav)
    assert "channels=2" in str(exc_info.value)


def test_not_wav_raises():
    with pytest.raises(WavFormatError):
        validate_wav_format(b"this is not a wav file at all")


def test_empty_bytes_raises():
    with pytest.raises(WavFormatError):
        validate_wav_format(b"")


# ==============================================================================
# TEST SUITE — BLOCK 2: extract_audio_info
# ==============================================================================


def test_duration_correct():
    wav = _make_wav(duration_s=2.0)
    wf = validate_wav_format(wav)
    dur, _, _ = extract_audio_info(wf)
    wf.close()
    assert _approx(dur, 2.0, 0.01)


def test_silent_wav_low_rms():
    wav = _make_wav(amplitude=0)
    wf = validate_wav_format(wav)
    _, rms_db, peak_db = extract_audio_info(wf)
    wf.close()
    assert rms_db == -math.inf or rms_db < -60


def test_loud_wav_high_rms():
    wav = _make_wav(amplitude=16000)
    wf = validate_wav_format(wav)
    _, rms_db, _ = extract_audio_info(wf)
    wf.close()
    assert rms_db > -30


# ==============================================================================
# TEST SUITE — BLOCK 3: detect_speech_boundaries
# ==============================================================================


def test_speech_boundaries_detected():
    # 0.3s im + 1.4s nói + 0.3s im
    wav = _make_wav(duration_s=2.0, amplitude=8000, silent_start_s=0.3, silent_end_s=0.3)
    wf = validate_wav_format(wav)
    start, end = detect_speech_boundaries(wf)
    wf.close()
    assert start < 0.5  # phát hiện trước 0.5s
    assert end > 1.2  # kéo dài sau 1.2s
    assert end > start


def test_silent_wav_no_boundary():
    wav = _make_wav(amplitude=0)
    wf = validate_wav_format(wav)
    start, end = detect_speech_boundaries(wf)
    wf.close()
    assert start == 0.0 and end == 0.0


# ==============================================================================
# TEST SUITE — BLOCK 4: validate_speech_content
# ==============================================================================


def test_too_short_raises():
    with pytest.raises(AudioContentError) as exc_info:
        validate_speech_content(total_duration_s=2.0, speech_duration_s=0.1, rms_db=-20.0)
    assert exc_info.value.error_code == "TOO_SHORT"


def test_too_quiet_raises():
    with pytest.raises(AudioContentError) as exc_info:
        validate_speech_content(total_duration_s=2.0, speech_duration_s=1.0, rms_db=-70.0)
    assert exc_info.value.error_code == "TOO_QUIET"


def test_too_long_raises():
    with pytest.raises(AudioContentError) as exc_info:
        validate_speech_content(total_duration_s=20.0, speech_duration_s=1.0, rms_db=-20.0)
    assert exc_info.value.error_code == "TOO_LONG"


def test_valid_content_passes():
    result = validate_speech_content(
        total_duration_s=2.0, speech_duration_s=1.0, rms_db=-20.0
    )
    assert result is None


# ==============================================================================
# TEST SUITE — BLOCK 5: trim_silence
# ==============================================================================


def test_trim_produces_valid_wav():
    wav = _make_wav(duration_s=2.0, amplitude=8000, silent_start_s=0.3, silent_end_s=0.3)
    wf = validate_wav_format(wav)
    start, end = detect_speech_boundaries(wf)
    trimmed = trim_silence(wf, start, end)
    wf.close()
    # trimmed phải là WAV hợp lệ
    wf2 = validate_wav_format(trimmed)
    dur2, _, _ = extract_audio_info(wf2)
    wf2.close()
    # trimmed ngắn hơn file gốc (đã cắt bớt im lặng)
    assert dur2 < 2.0


def test_trim_shorter_than_original():
    wav = _make_wav(duration_s=3.0, amplitude=8000, silent_start_s=0.5, silent_end_s=0.5)
    wf = validate_wav_format(wav)
    start, end = detect_speech_boundaries(wf)
    trimmed = trim_silence(wf, start, end)
    wf.close()
    wf2 = validate_wav_format(trimmed)
    dur2, _, _ = extract_audio_info(wf2)
    wf2.close()
    assert dur2 < 3.0


# ==============================================================================
# TEST SUITE — BLOCK 6: process_audio (integration)
# ==============================================================================


def test_process_audio_full_pipeline():
    wav = _make_wav(duration_s=2.0, amplitude=8000)
    info = process_audio(wav)
    assert info.sample_rate == REQUIRED_SAMPLE_RATE
    assert info.channels == REQUIRED_CHANNELS
    assert info.speech_duration_s > 0
    assert len(info.trimmed_wav_bytes) > 44  # > WAV header size
    assert info.rms_db > -60


def test_process_audio_wrong_format_raises():
    wav = _make_wav(sample_rate=44100)
    with pytest.raises(WavFormatError):
        process_audio(wav)


def test_process_audio_silent_raises():
    wav = _make_wav(amplitude=0)
    with pytest.raises(AudioContentError) as exc_info:
        process_audio(wav)
    assert exc_info.value.error_code in ("TOO_SHORT", "TOO_QUIET")


def test_audio_info_to_dict_no_bytes():
    wav = _make_wav(duration_s=2.0, amplitude=8000)
    info = process_audio(wav)
    d = info.to_dict()
    assert "trimmed_wav_bytes" not in d
    assert "trimmed_wav_size_bytes" in d
    assert d["sample_rate"] == REQUIRED_SAMPLE_RATE
