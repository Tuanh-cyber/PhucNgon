#!/usr/bin/env python3
"""
Seed dữ liệu Color Recognition từ color_recognition/Color Recognition Asset.xlsx.

An toàn chạy lại (idempotent): xóa sạch 2 bảng color rồi nạp lại.
KHÔNG đụng dữ liệu bài nói / logic_sequence.

  python -m scripts.seed_colors
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import SessionLocal
from app.models.color_recognition import Color, ColorRecognitionExercise

XLSX = Path(__file__).parent.parent / "color_recognition" / "Color Recognition Asset.xlsx"


def _parse_profiles(raw) -> list[str]:
    if pd.isna(raw):
        return []
    return [p.strip() for p in str(raw).split(",") if p.strip()]


def main() -> None:
    colors_df = pd.read_excel(XLSX, sheet_name="Color Asset")
    meta_df = pd.read_excel(XLSX, sheet_name="Metadata")

    db = SessionLocal()
    try:
        db.query(ColorRecognitionExercise).delete()
        db.query(Color).delete()
        db.flush()

        color_by_code: dict[str, Color] = {}
        for _, r in colors_df.iterrows():
            c = Color(
                color_id=str(r["ID"]),
                name=str(r["Color Name"]),
                hex_code=str(r["Hex Code"]),
                image_file=str(r["Image File"]) if not pd.isna(r["Image File"]) else None,
            )
            db.add(c)
            db.flush()
            color_by_code[c.color_id] = c

        n_ex = 0
        for _, r in meta_df.iterrows():
            target = color_by_code.get(str(r["target_color_id"]))
            if target is None:
                print(f"⚠️ BỎ QUA {r['exercise_id']}: không thấy màu {r['target_color_id']}")
                continue
            db.add(
                ColorRecognitionExercise(
                    exercise_code=str(r["exercise_id"]),
                    exercise_type=str(r["exercise_type"]),
                    target_color_id=target.id,
                    instruction_audio=str(r["instruction_audio"]),
                    level=int(r["level"]),
                    suitable_profiles=_parse_profiles(r["suitable_profiles"]),
                )
            )
            n_ex += 1

        db.commit()
        print(f"✓ Seed Color Recognition xong: {len(color_by_code)} colors, {n_ex} exercises.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
