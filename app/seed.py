#!/usr/bin/env python3
"""
Seed database từ Excel files.

Sử dụng:
  python -m app.seed

Hoặc chỉ định đường dẫn custom:
  python -m app.seed --asset-path /path/to/Asset.xlsx --exercise-bank-path /path/to/Exercise_bank.xlsx
"""

import sys
from pathlib import Path

# Gọi seed script từ scripts/
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.seed_from_excel import main as seed_main

if __name__ == "__main__":
    # Nếu không set đường dẫn, dùng default (Exercise_data/ nằm ở gốc repo)
    import argparse

    parser = argparse.ArgumentParser(
        description="Seed database from Exercise_data/ Excel files"
    )
    parser.add_argument(
        "--asset-path",
        type=str,
        default=str(Path(__file__).parent.parent / "Exercise_data" / "Asset.xlsx"),
        help="Path to Asset.xlsx (default: Exercise_data/Asset.xlsx)",
    )
    parser.add_argument(
        "--exercise-bank-path",
        type=str,
        default=str(Path(__file__).parent.parent / "Exercise_data" / "Exercise_bank.xlsx"),
        help="Path to Exercise_bank.xlsx (default: Exercise_data/Exercise_bank.xlsx)",
    )
    args = parser.parse_args()

    # Reconstruct argv cho seed_from_excel.main()
    sys.argv = [
        sys.argv[0],
        "--asset-path",
        args.asset_path,
        "--exercise-bank-path",
        args.exercise_bank_path,
    ]

    seed_main()
