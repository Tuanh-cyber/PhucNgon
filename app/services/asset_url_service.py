"""
Asset URL service — build đường dẫn /static/... cho ảnh/audio bài tập.

Nguyên tắc: CHỈ trả URL khi file thật sự tồn tại trên đĩa (đọc gốc từ
settings.STATIC_ASSETS_BASE_DIR); file thiếu/field NULL -> trả None để frontend hiện
placeholder/ẩn nút thay vì gọi 1 URL 404. Điều này quan trọng vì audio vocab CHƯA có,
và 1 số ảnh/audio có thể thiếu lẻ tẻ.

Mapping topic enum (DB) -> tên thư mục ảnh THẬT trên đĩa (Picture/{folder}/):
  daily_activity -> Activity | food_drink -> Food&Drink | household_item -> Object
  family -> Family | body_part -> Body | number -> Number
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import quote

from app.core.config import settings
from app.models.content import CommandAsset, SentenceInstanceAsset, VocabularyAsset

# Tên thư mục con ảnh theo topic — khớp cấu trúc thật của Picture/ trên đĩa.
TOPIC_PICTURE_FOLDER: dict[str, str] = {
    "daily_activity": "Activity",
    "food_drink": "Food&Drink",
    "household_item": "Object",
    "family": "Family",
    "body_part": "Body",
    "number": "Number",
}

# (route mount trong main.py, thư mục thật trên đĩa)
_PICTURES_ROUTE, _PICTURES_DIR = "/static/pictures", "Picture"
_CMD_AUDIO_ROUTE, _CMD_AUDIO_DIR = "/static/command-audio", "command_audio_wav"
_SENT_AUDIO_ROUTE, _SENT_AUDIO_DIR = "/static/sentence-audio", "sentence_instance_wav"
_VOCAB_AUDIO_ROUTE, _VOCAB_AUDIO_DIR = "/static/vocab-audio", "Vocab"


def _base_dir() -> Path:
    return Path(settings.STATIC_ASSETS_BASE_DIR)


def _url_if_exists(route: str, dirname: str, *parts: str) -> Optional[str]:
    """Trả '{route}/{parts...}' (đã URL-encode từng phần) nếu file tồn tại, ngược lại None."""
    if not parts or any(p is None or p == "" for p in parts):
        return None
    file_path = _base_dir() / dirname
    for p in parts:
        file_path = file_path / p
    if not file_path.is_file():
        return None
    # quote từng phần: thư mục "Food&Drink" và tên file tiếng Việt cần encode.
    encoded = "/".join(quote(p) for p in parts)
    return f"{route}/{encoded}"


def vocab_image_url(vocab: Optional[VocabularyAsset]) -> Optional[str]:
    """URL ảnh của 1 từ vựng: /static/pictures/{TopicFolder}/{image_file}. Thiếu -> None."""
    if vocab is None or not vocab.image_file:
        return None
    folder = TOPIC_PICTURE_FOLDER.get(vocab.topic.value)
    if folder is None:
        return None
    return _url_if_exists(_PICTURES_ROUTE, _PICTURES_DIR, folder, vocab.image_file)


def vocab_audio_url(vocab: Optional[VocabularyAsset]) -> Optional[str]:
    """URL audio phát âm từ vựng: /static/vocab-audio/{audio_file}. Thiếu -> None."""
    if vocab is None or not vocab.audio_file:
        return None
    return _url_if_exists(_VOCAB_AUDIO_ROUTE, _VOCAB_AUDIO_DIR, vocab.audio_file)


def command_audio_url(command: Optional[CommandAsset]) -> Optional[str]:
    """URL audio câu hỏi bài Nghe và đoán: /static/command-audio/{file}. Thiếu -> None."""
    if command is None or not command.command_audio_file:
        return None
    return _url_if_exists(_CMD_AUDIO_ROUTE, _CMD_AUDIO_DIR, command.command_audio_file)


def sentence_audio_url(si: Optional[SentenceInstanceAsset]) -> Optional[str]:
    """URL audio câu mẫu bài Hoàn thành câu: /static/sentence-audio/{file}. Thiếu -> None."""
    if si is None or not si.audio_file:
        return None
    return _url_if_exists(_SENT_AUDIO_ROUTE, _SENT_AUDIO_DIR, si.audio_file)
