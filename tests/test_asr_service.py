"""
Test suite cho app.services.asr_service — 2 chế độ fake / real.

Dùng monkeypatch (tự động undo sau mỗi test) để đổi settings.ASR_MODE và mock httpx,
KHÔNG gọi service ASR thật của Vy, KHÔNG để rò rỉ ASR_MODE sang test khác.
"""

import httpx
import pytest

from app.core.config import settings
from app.services import asr_service
from app.services.asr_service import transcribe_audio


def test_transcribe_fake_mode(monkeypatch):
    """ASR_MODE='fake' -> trả kết quả cố định, KHÔNG gọi service thật.

    Ép fake bằng monkeypatch (không phụ thuộc giá trị ASR_MODE trong .env của môi trường —
    ví dụ khi deploy/bật real, test này vẫn phải xanh)."""
    monkeypatch.setattr(settings, "ASR_MODE", "fake")
    result = transcribe_audio(b"fake-wav-bytes")
    assert result == {"transcript": "cái kéo", "confidence": 0.9}


def test_transcribe_real_mode_calls_http(monkeypatch):
    """ASR_MODE='real' -> gọi HTTP (mock), map json['text'] -> transcript, confidence=1.0."""
    monkeypatch.setattr(settings, "ASR_MODE", "real")

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {"text": "con mèo", "processing_time": 1.2}

    def _fake_post(url, **kwargs):
        # Xác nhận gửi đúng field multipart "audio"
        assert "files" in kwargs and "audio" in kwargs["files"]
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", _fake_post)

    result = transcribe_audio(b"fake-wav-bytes")
    assert result == {"transcript": "con mèo", "confidence": 1.0}


def test_transcribe_invalid_mode_raises(monkeypatch):
    """ASR_MODE lạ -> ValueError rõ ràng."""
    monkeypatch.setattr(settings, "ASR_MODE", "abc")
    with pytest.raises(ValueError):
        transcribe_audio(b"fake-wav-bytes")


def test_transcribe_real_mode_connect_error_raises(monkeypatch):
    """ASR_MODE='real' nhưng service chết -> RuntimeError (không nuốt lỗi)."""
    monkeypatch.setattr(settings, "ASR_MODE", "real")

    def _boom(url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _boom)
    with pytest.raises(RuntimeError):
        transcribe_audio(b"fake-wav-bytes")
