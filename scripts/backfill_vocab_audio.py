"""
Backfill cột audio_file cho vocabulary_assets từ Asset.xlsx (sheet Vocabulary) + thư mục Vocab/.

BỐI CẢNH: DB seed trước khi Excel có cột audio_file (hiện 0/90 dòng có giá trị), trong khi
file .wav đã có thật trong thư mục Vocab/ (cùng cấp repo), đặt tên theo mã vocab trong Excel
(vd VFA1001.wav — cùng pattern với image_file VFA1001.jpg).

DB không lưu mã Excel (chỉ UUID) -> khớp bằng NATURAL KEY image_file (duy nhất mỗi dòng,
'{vocab_id}.jpg'). CHỈ UPDATE khi file .wav thật sự tồn tại trong Vocab/ — tránh trỏ tới file
ma (frontend sẽ ẩn nút nghe khi audio_url null, nhưng null "trung thực" tốt hơn URL 404).

Idempotent: chạy lại nhiều lần không sao. KHÔNG cần migration (cột đã tồn tại).
Chạy:  python -m scripts.backfill_vocab_audio
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.content import VocabularyAsset

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EXCEL_PATH = Path(__file__).resolve().parents[1] / "Exercise_data" / "Asset.xlsx"
VOCAB_AUDIO_DIR = Path(settings.STATIC_ASSETS_BASE_DIR) / "Vocab"


def _norm(s: object) -> str:
    return " ".join(str(s).split())


def main() -> int:
    if not EXCEL_PATH.exists():
        logger.error("Không tìm thấy %s", EXCEL_PATH)
        return 1
    if not VOCAB_AUDIO_DIR.is_dir():
        logger.error("Không tìm thấy thư mục audio vocab: %s", VOCAB_AUDIO_DIR)
        return 1

    df = pd.read_excel(EXCEL_PATH, sheet_name="Vocabulary")
    # image_file -> audio_file (cả 2 đều '{vocab_id}.*' — image_file là natural key duy nhất)
    audio_by_image: dict[str, str] = {}
    for _, row in df.iterrows():
        if pd.notna(row.get("image_file")) and pd.notna(row.get("audio_file")):
            audio_by_image[_norm(row["image_file"])] = _norm(row["audio_file"])

    db = SessionLocal()
    try:
        updated = missing_excel = missing_file = 0
        for vocab in db.query(VocabularyAsset).all():
            audio_name = audio_by_image.get(_norm(vocab.image_file or ""))
            if not audio_name:
                missing_excel += 1
                logger.warning(
                    "Không khớp Excel cho vocab %r (image_file=%r)",
                    vocab.canonical_word, vocab.image_file,
                )
                continue
            if not (VOCAB_AUDIO_DIR / audio_name).is_file():
                missing_file += 1
                logger.warning(
                    "Excel ghi %r nhưng file KHÔNG có trong %s (vocab %r) — bỏ qua",
                    audio_name, VOCAB_AUDIO_DIR, vocab.canonical_word,
                )
                continue
            vocab.audio_file = audio_name
            updated += 1

        db.commit()
        logger.info(
            "✓ Backfill vocab audio xong: %d cập nhật / %d không khớp Excel / %d thiếu file .wav",
            updated, missing_excel, missing_file,
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
