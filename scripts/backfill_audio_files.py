"""
Backfill audio filenames cho CommandAsset + SentenceInstanceAsset từ Exercise_data/Asset.xlsx.

BỐI CẢNH: DB được seed TRƯỚC KHI cột audio trong Excel có giá trị, nên hiện tại
command_assets.command_audio_file và sentence_instance_assets.audio_file đều NULL — trong khi
file .wav đã có thật trên đĩa, đặt tên theo MÃ asset trong Excel:
  - command_audio_wav/{command_id}.wav        (vd C001.wav)
  - sentence_instance_wav/{sentence_instance_id}.wav  (vd SI001.wav)

DB không lưu mã Excel (chỉ có UUID), nên script này khớp lại bằng KHÓA ĐỊNH DANH:
  - CommandAsset          <-> Excel sheet "Command"           qua command_text
  - SentenceInstanceAsset <-> Excel sheet "Sentence Instance" qua CẶP (template, vocab)
      Mỗi sentence_instance_id trong Excel = 1 cặp (template_id, vocab_id) duy nhất.
      DB giữ FK template_id/vocab_id (UUID) -> tra ngược ra text template + canonical_word
      -> khớp với Excel qua cặp này. KHÔNG khớp theo full_sentence nữa (mong manh: sửa
      câu trong Excel sau khi seed sẽ ghép audio sai bài).
      File .wav phải TỒN TẠI trong sentence_instance_wav/ mới gán; thiếu -> để NULL + log.

Idempotent: chạy lại nhiều lần không sao (chỉ UPDATE giá trị filename).
Chạy:  python -m scripts.backfill_audio_files
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.content import CommandAsset, SentenceInstanceAsset

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EXCEL_PATH = Path(__file__).resolve().parents[1] / "Exercise_data" / "Asset.xlsx"
# Thư mục .wav câu mẫu — cùng gốc static với asset_url_service (_SENT_AUDIO_DIR).
SENTENCE_WAV_DIR = Path(settings.STATIC_ASSETS_BASE_DIR) / "sentence_instance_wav"


def _norm(s: object) -> str:
    """Chuẩn hoá chuỗi để so khớp: strip + gộp khoảng trắng."""
    return " ".join(str(s).split())


def main() -> int:
    if not EXCEL_PATH.exists():
        logger.error("Không tìm thấy %s", EXCEL_PATH)
        return 1

    command_df = pd.read_excel(EXCEL_PATH, sheet_name="Command")
    si_df = pd.read_excel(EXCEL_PATH, sheet_name="Sentence Instance")
    template_df = pd.read_excel(EXCEL_PATH, sheet_name="Sentence Template")
    vocab_df = pd.read_excel(EXCEL_PATH, sheet_name="Vocabulary")

    # command_text -> tên file audio (ưu tiên cột command_audio_file; thiếu thì suy từ mã).
    cmd_audio_by_text: dict[str, str] = {}
    for _, row in command_df.iterrows():
        audio = row.get("command_audio_file")
        filename = (
            _norm(audio) if pd.notna(audio) else f"{_norm(row['command_id'])}.wav"
        )
        cmd_audio_by_text[_norm(row["command_text"])] = filename

    # KHÓA ĐỊNH DANH cho sentence instance: cặp (template text, canonical_word).
    # Excel: sentence_instance_id <-> (template_id, vocab_id) là 1-1; tra 2 sheet phụ để
    # đổi mã Excel (T001/VFD1001) ra text — DB cũng tra ngược FK ra đúng cặp text này.
    tmpl_text_by_code = {
        _norm(r["template_id"]): _norm(r["template"]) for _, r in template_df.iterrows()
    }
    vocab_word_by_code = {
        _norm(r["vocab_id"]): _norm(r["canonical_word"]) for _, r in vocab_df.iterrows()
    }
    si_audio_by_pair: dict[tuple[str, str], tuple[str, str]] = {}
    for _, row in si_df.iterrows():
        audio = row.get("sentence_audio_file")
        filename = (
            _norm(audio) if pd.notna(audio) else f"{_norm(row['sentence_instance_id'])}.wav"
        )
        key = (
            tmpl_text_by_code.get(_norm(row["template_id"]), ""),
            vocab_word_by_code.get(_norm(row["vocab_id"]), ""),
        )
        si_audio_by_pair[key] = (_norm(row["sentence_instance_id"]), filename)

    db = SessionLocal()
    try:
        cmd_updated = cmd_missed = 0
        for cmd in db.query(CommandAsset).all():
            filename = cmd_audio_by_text.get(_norm(cmd.command_text))
            if filename:
                cmd.command_audio_file = filename
                cmd_updated += 1
            else:
                cmd_missed += 1
                logger.warning("Không khớp Excel cho command_text=%r", cmd.command_text)

        si_updated = si_missed = si_no_wav = 0
        for si in db.query(SentenceInstanceAsset).all():
            key = (_norm(si.template.template), _norm(si.vocab.canonical_word))
            hit = si_audio_by_pair.get(key)
            if not hit:
                si_missed += 1
                logger.warning(
                    "Không khớp Excel cho (template=%r, vocab=%r) — full_sentence=%r",
                    key[0], key[1], si.full_sentence,
                )
                continue
            si_code, filename = hit
            if not (SENTENCE_WAV_DIR / filename).is_file():
                # Thiếu file thật trên đĩa -> để NULL (frontend ẩn nút nghe), không crash.
                si.audio_file = None
                si_no_wav += 1
                logger.warning(
                    "%s: file %s KHÔNG tồn tại trong %s -> audio_file=NULL",
                    si_code, filename, SENTENCE_WAV_DIR,
                )
                continue
            si.audio_file = filename
            si_updated += 1

        db.commit()
        logger.info(
            "✓ Backfill xong: command %d cập nhật / %d không khớp; "
            "sentence_instance %d cập nhật / %d không khớp Excel / %d thiếu file wav",
            cmd_updated, cmd_missed, si_updated, si_missed, si_no_wav,
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
