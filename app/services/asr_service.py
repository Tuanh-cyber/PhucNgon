"""
PhụcNgôn — ASR SERVICE (2 chế độ: fake / real)
================================================================================
Owner: Vy  |  Module 2 (ASR - Automatic Speech Recognition)

Chế độ hiện tại đọc từ settings.ASR_MODE (mặc định 'fake'). Khi Vy hoàn thiện finetune
PhoWhisper, đổi ASR_MODE='real' trong .env — KHÔNG cần sửa file này hay bất kỳ file nào khác.

Interface public CỐ ĐỊNH: def transcribe_audio(wav_bytes: bytes) -> dict
  {"transcript": str, "confidence": float}
Mọi nơi gọi (session_service.submit_attempt, process_attempt_preview) dùng đúng hàm này.
"""

from __future__ import annotations

import httpx


def _transcribe_fake(wav_bytes: bytes) -> dict:
    """
    Hàm giả — dùng cho test và phát triển các phần khác của hệ thống, KHÔNG phụ thuộc Vy.
    Trả cố định 1 kết quả hợp lý để các phần downstream (scoring) chạy được bình thường.
    """
    return {"transcript": "cái kéo", "confidence": 0.9}


def _transcribe_real(wav_bytes: bytes) -> dict:
    """
    Gọi HTTP thật tới ASR service của Vy (PhoWhisper). CHỈ dùng khi ASR_MODE="real".

    - POST multipart/form-data, field "audio" = wav_bytes, tới {ASR_SERVICE_URL}/transcribe,
      timeout 30s (cho cold start Modal lần đầu).
    - Map response: transcript = json["text"]; confidence = 1.0 (Vy hiện chưa trả confidence
      thật -> dùng mặc định trung tính, khớp giá trị mặc định asr_confidence của score()).
    - Mỗi loại lỗi -> RuntimeError với message tiếng Việt riêng biệt (không nuốt lỗi).
    """
    from app.core.config import settings

    asr_url = f"{settings.ASR_SERVICE_URL}/transcribe"
    try:
        response = httpx.post(
            asr_url,
            files={"audio": ("audio.wav", wav_bytes, "audio/wav")},
            timeout=30.0,
        )
    except httpx.TimeoutException as e:
        # Bắt Timeout TRƯỚC RequestError (TimeoutException là subclass của RequestError).
        raise RuntimeError(
            f"ASR service phản hồi quá chậm (>30s) tại {asr_url} — "
            f"có thể model đang xử lý quá lâu (cold start?). Chi tiết: {e}"
        )
    except httpx.RequestError as e:
        # Gồm ConnectError + mọi lỗi mạng khác (ReadError, ProtocolError, DNS...).
        raise RuntimeError(
            f"Không kết nối được tới ASR service ({asr_url}) — "
            f"kiểm tra service của Vy đã chạy chưa. Chi tiết: {e}"
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"ASR service trả lỗi HTTP {response.status_code} tại {asr_url}: "
            f"{response.text[:200]}"
        )

    # Response của Vy (POST /transcribe trả {"text": str, ...}):
    #   {"text": str, ...}  (Vy chưa trả confidence trong response)
    # Vy chưa trả confidence -> 1.0 trung tính (khớp mặc định asr_confidence của score()).
    try:
        data = response.json()
        transcript = data["text"]
    except (ValueError, KeyError, TypeError) as e:
        raise RuntimeError(
            f"ASR service trả response sai hình dạng (cần JSON có field 'text') tại "
            f"{asr_url}: {response.text[:200]!r}. Chi tiết: {e}"
        )
    return {"transcript": transcript, "confidence": 1.0}


def transcribe_audio(wav_bytes: bytes) -> dict:
    """
    Hàm điều phối — chọn fake hay real dựa theo settings.ASR_MODE.
    """
    from app.core.config import settings

    if settings.ASR_MODE == "real":
        return _transcribe_real(wav_bytes)
    elif settings.ASR_MODE == "fake":
        return _transcribe_fake(wav_bytes)
    else:
        raise ValueError(
            f"ASR_MODE='{settings.ASR_MODE}' không hợp lệ — chỉ chấp nhận 'fake' hoặc 'real'"
        )
