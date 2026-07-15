#!/usr/bin/env python3
"""
Seed dữ liệu Logic Sequence từ logic_sequence/Sequence Asset.xlsx.

An toàn chạy lại (idempotent): xóa sạch 3 bảng sequence rồi nạp lại.
KHÔNG đụng dữ liệu bài nói (vocab/command/sentence/exercises).

  python -m scripts.seed_sequences
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import SessionLocal
from app.models.sequence import LogicSequenceExercise, Sequence, SequenceStep

XLSX = Path(__file__).parent.parent / "logic_sequence" / "Sequence Asset.xlsx"


def _parse_profiles(raw) -> list[str]:
    if pd.isna(raw):
        return []
    return [p.strip() for p in str(raw).split(",") if p.strip()]


def main() -> None:
    asset = pd.read_excel(XLSX, sheet_name="asset")
    meta = pd.read_excel(XLSX, sheet_name="exercise metadata")

    db = SessionLocal()
    try:
        # Clear (con -> cha): exercises trỏ sequences; steps cascade từ sequences.
        db.query(LogicSequenceExercise).delete()
        db.query(SequenceStep).delete()
        db.query(Sequence).delete()
        db.flush()

        # Sequences + steps
        seq_by_code: dict[str, Sequence] = {}
        for code, grp in asset.groupby("sequence_id"):
            grp = grp.sort_values("step_order")
            seq = Sequence(
                sequence_id=str(code),
                title=str(grp.iloc[0]["title"]),
                level=int(grp.iloc[0]["level"]),
                step_count=len(grp),
            )
            db.add(seq)
            db.flush()
            for _, row in grp.iterrows():
                db.add(
                    SequenceStep(
                        sequence_id=seq.id,
                        step_order=int(row["step_order"]),
                        image_file=str(row["image_file"]),
                    )
                )
            seq_by_code[str(code)] = seq

        # Exercises
        n_ex = 0
        for _, row in meta.iterrows():
            target = seq_by_code.get(str(row["target_sequence_id"]))
            if target is None:
                print(f"⚠️ BỎ QUA {row['exercise_id']}: không tìm thấy sequence {row['target_sequence_id']}")
                continue
            db.add(
                LogicSequenceExercise(
                    exercise_code=str(row["exercise_id"]),
                    exercise_type=str(row["exercise_type"]),
                    target_sequence_id=target.id,
                    suitable_profiles=_parse_profiles(row["suitable_profiles"]),
                )
            )
            n_ex += 1

        db.commit()
        print(
            f"✓ Seed Logic Sequence xong: {len(seq_by_code)} sequences, "
            f"{len(asset)} steps, {n_ex} exercises."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
