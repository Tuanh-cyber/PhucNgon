"""
Sửa 1 dòng command_assets bị dính artifact Excel trong command_text.

Dòng lỗi (seed từ Excel cũ có lỗi copy-paste công thức):
  "Hành độn+B2:B63g làm sạch bàn tay bằng nước và xà phòng gọi là gì?"
Giá trị đúng theo Exercise_data/Asset.xlsx hiện tại:
  "Hành động làm sạch bàn tay bằng nước và xà phòng gọi là gì?"

Sau khi sửa text, gán luôn command_audio_file cho dòng này bằng đúng logic backfill
(khớp command_text đã sửa với sheet "Command" -> lấy command_audio_file / suy từ command_id).

Idempotent: chạy lại khi dòng đã đúng sẽ báo "không có gì để sửa".
Chạy:  python -m scripts.fix_command_text
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

from app.core.database import SessionLocal
from app.models.content import CommandAsset

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EXCEL_PATH = Path(__file__).resolve().parents[1] / "Exercise_data" / "Asset.xlsx"

# Artifact nhận diện dòng lỗi (khớp mềm — chỉ cần chứa chuỗi này).
BROKEN_MARKER = "B2:B63"
CORRECT_TEXT = "Hành động làm sạch bàn tay bằng nước và xà phòng gọi là gì?"


def _norm(s: object) -> str:
    return " ".join(str(s).split())


def main() -> int:
    db = SessionLocal()
    try:
        broken = (
            db.query(CommandAsset)
            .filter(CommandAsset.command_text.like(f"%{BROKEN_MARKER}%"))
            .all()
        )
        if not broken:
            logger.info("Không có dòng nào chứa artifact %r — không có gì để sửa.", BROKEN_MARKER)
            return 0
        if len(broken) > 1:
            logger.error(
                "Tìm thấy %d dòng chứa %r — script này chỉ dành cho đúng 1 dòng, "
                "dừng lại để tránh sửa nhầm.", len(broken), BROKEN_MARKER,
            )
            return 1

        row = broken[0]
        logger.info("Dòng lỗi (id=%s): %r", row.id, row.command_text)

        # 1) Sửa text về giá trị đúng
        row.command_text = CORRECT_TEXT

        # 2) Backfill audio cho riêng dòng này — cùng logic scripts/backfill_audio_files.py
        audio_file = None
        if EXCEL_PATH.exists():
            command_df = pd.read_excel(EXCEL_PATH, sheet_name="Command")
            for _, xrow in command_df.iterrows():
                if _norm(xrow["command_text"]) == _norm(CORRECT_TEXT):
                    raw_audio = xrow.get("command_audio_file")
                    audio_file = (
                        _norm(raw_audio)
                        if pd.notna(raw_audio)
                        else f"{_norm(xrow['command_id'])}.wav"
                    )
                    break
            if audio_file is None:
                logger.warning(
                    "Excel không có dòng khớp text đúng — command_audio_file giữ nguyên (%r).",
                    row.command_audio_file,
                )
        else:
            logger.warning("Không tìm thấy %s — bỏ qua bước gán audio.", EXCEL_PATH)

        if audio_file:
            row.command_audio_file = audio_file

        db.commit()
        logger.info(
            "✓ Đã cập nhật 1 dòng: command_text=%r, command_audio_file=%r",
            row.command_text, row.command_audio_file,
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
