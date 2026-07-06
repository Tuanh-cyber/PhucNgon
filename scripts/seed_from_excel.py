#!/usr/bin/env python3
"""ETL script: Read Excel files and seed PostgreSQL database."""

import argparse
import logging
import sys
import uuid as uuid_module
from pathlib import Path

import pandas as pd
from sqlalchemy import delete
from sqlalchemy.orm import Session

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import SessionLocal
from app.models.content import (
    CommandAsset,
    Exercise,
    SentenceInstanceAsset,
    SentenceTemplateAsset,
    VocabularyAsset,
)
from app.models.enums import CommandMode, ExerciseType, Topic, WordType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ── Mapping tables ────────────────────────────────────────────────────────────
TOPIC_MAP = {
    "Hoạt động thường ngày": "daily_activity",
    "Ăn uống": "food_drink",
    "Vật dụng": "household_item",
    "Gia đình": "family",
    "Bộ phận cơ thể": "body_part",
    "Số đếm": "number",
}

WORD_TYPE_VALUES = {"noun", "verb", "adjective"}
COMMAND_MODE_VALUES = {"recognition", "repetition"}
EXERCISE_TYPE_VALUES = {"naming", "command_identification", "sentence_building"}


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Seed database from Excel files")
    parser.add_argument(
        "--asset-path",
        type=str,
        required=True,
        help="Path to Asset.xlsx",
    )
    parser.add_argument(
        "--exercise-bank-path",
        type=str,
        required=True,
        help="Path to Exercise_bank.xlsx",
    )
    return parser.parse_args()


def parse_comma_separated_string(value):
    """Convert comma-separated string to list of stripped values, excluding empty strings."""
    if pd.isna(value) or value == "":
        return []
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    return []


def convert_nan_to_none(value):
    """Convert pandas NaN to Python None."""
    if pd.isna(value):
        return None
    return value


def read_and_validate_raw_data(asset_path: str, exercise_bank_path: str):
    """Step 1: Read and validate raw data from Excel files."""
    logger.info("=" * 80)
    logger.info("STEP 1: Reading and validating raw data")
    logger.info("=" * 80)

    # Read sheets
    logger.info(f"Reading sheets from {asset_path}")
    vocab_df = pd.read_excel(asset_path, sheet_name="Vocabulary")
    command_df = pd.read_excel(asset_path, sheet_name="Command")
    sentence_template_df = pd.read_excel(asset_path, sheet_name="Sentence Template")
    sentence_instance_df = pd.read_excel(asset_path, sheet_name="Sentence Instance")

    logger.info(f"Reading sheets from {exercise_bank_path}")
    naming_df = pd.read_excel(exercise_bank_path, sheet_name="NAMING")
    command_id_df = pd.read_excel(exercise_bank_path, sheet_name="COMMAND IDENTIFICATION")
    sentence_building_df = pd.read_excel(
        exercise_bank_path, sheet_name="SENTENCE BUILDING"
    )

    # Print row counts
    logger.info(f"Vocabulary: {len(vocab_df)} rows")
    logger.info(f"Command: {len(command_df)} rows")
    logger.info(f"Sentence Template: {len(sentence_template_df)} rows")
    logger.info(f"Sentence Instance: {len(sentence_instance_df)} rows")
    logger.info(f"NAMING exercises: {len(naming_df)} rows")
    logger.info(f"COMMAND IDENTIFICATION exercises: {len(command_id_df)} rows")
    logger.info(f"SENTENCE BUILDING exercises: {len(sentence_building_df)} rows")

    # Validate required columns
    logger.info("\nValidating column names...")
    required_columns = {
        "vocab_df": ["vocab_id", "canonical_word", "accepted_answers", "topic", "word_type"],
        "command_df": ["command_id", "command_text", "command_audio_file", "target_vocab_id"],
        "sentence_template_df": ["template_id", "template", "topic_constraint"],
        "sentence_instance_df": [
            "sentence_instance_id",
            "template_id",
            "vocab_id",
            "full_sentence",
            "accepted_answers",
            "sentence_audio_file",
        ],
    }

    for df_name, df in [
        ("vocab_df", vocab_df),
        ("command_df", command_df),
        ("sentence_template_df", sentence_template_df),
        ("sentence_instance_df", sentence_instance_df),
    ]:
        missing_cols = set(required_columns[df_name]) - set(df.columns)
        if missing_cols:
            logger.error(f"{df_name} missing columns: {missing_cols}")
            logger.error(f"  Available columns: {list(df.columns)}")
            raise ValueError(f"{df_name} is missing required columns: {missing_cols}")

    required_exercise_cols = ["exercise_id", "exercise_type", "suitable_profiles"]

    for sheet_name, df in [
        ("NAMING", naming_df),
        ("COMMAND IDENTIFICATION", command_id_df),
        ("SENTENCE BUILDING", sentence_building_df),
    ]:
        missing_cols = set(required_exercise_cols) - set(df.columns)
        if missing_cols:
            logger.error(f"{sheet_name} missing columns: {missing_cols}")
            logger.error(f"  Available columns: {list(df.columns)}")
            raise ValueError(f"{sheet_name} is missing required columns: {missing_cols}")
        if sheet_name == "COMMAND IDENTIFICATION" and "mode" not in df.columns:
            logger.error(f"{sheet_name} missing 'mode' column")
            raise ValueError(f"{sheet_name} is missing 'mode' column")
        if sheet_name == "NAMING" and "target_vocab_id" not in df.columns:
            logger.error(f"{sheet_name} missing 'target_vocab_id' column")
            raise ValueError(f"{sheet_name} is missing 'target_vocab_id' column")
        if sheet_name == "COMMAND IDENTIFICATION" and "target_vocab_id" not in df.columns:
            logger.error(f"{sheet_name} missing 'target_vocab_id' column")
            raise ValueError(f"{sheet_name} is missing 'target_vocab_id' column")
        if (
            sheet_name == "SENTENCE BUILDING"
            and "target_sentence_instance_id" not in df.columns
        ):
            logger.error(f"{sheet_name} missing 'target_sentence_instance_id' column")
            raise ValueError(
                f"{sheet_name} is missing 'target_sentence_instance_id' column"
            )

    logger.info("✓ All required columns present")

    # Validate unique enum values
    logger.info("\nValidating enum values...")

    # Vocabulary.topic
    vocab_topics = vocab_df["topic"].dropna().unique()
    logger.info(f"Vocabulary topics found: {list(vocab_topics)}")
    unknown_topics = set(vocab_topics) - set(TOPIC_MAP.keys())
    if unknown_topics:
        raise ValueError(f"Unknown topics in Vocabulary: {unknown_topics}")

    # Vocabulary.word_type
    vocab_word_types = vocab_df["word_type"].dropna().unique()
    logger.info(f"Vocabulary word_types found: {list(vocab_word_types)}")
    unknown_word_types = set(vocab_word_types) - WORD_TYPE_VALUES
    if unknown_word_types:
        raise ValueError(f"Unknown word_types in Vocabulary: {unknown_word_types}")

    # Sentence Template.topic_constraint
    template_topics = sentence_template_df["topic_constraint"].dropna().unique()
    logger.info(f"Sentence Template topic_constraints found: {list(template_topics)}")
    unknown_template_topics = set(template_topics) - set(TOPIC_MAP.keys())
    if unknown_template_topics:
        raise ValueError(
            f"Unknown topic_constraints in Sentence Template: {unknown_template_topics}"
        )

    # Exercise.exercise_type
    naming_types = naming_df["exercise_type"].dropna().unique()
    cmd_types = command_id_df["exercise_type"].dropna().unique()
    sent_types = sentence_building_df["exercise_type"].dropna().unique()
    all_exercise_types = set(naming_types) | set(cmd_types) | set(sent_types)
    logger.info(f"Exercise types found: {list(all_exercise_types)}")
    unknown_exercise_types = all_exercise_types - EXERCISE_TYPE_VALUES
    if unknown_exercise_types:
        raise ValueError(f"Unknown exercise_types: {unknown_exercise_types}")

    # Exercise.mode (only for command_identification)
    cmd_modes = command_id_df["mode"].dropna().unique()
    logger.info(f"Command modes found: {list(cmd_modes)}")
    unknown_modes = set(cmd_modes) - COMMAND_MODE_VALUES
    if unknown_modes:
        raise ValueError(f"Unknown modes in COMMAND IDENTIFICATION: {unknown_modes}")

    logger.info("✓ All enum values are valid\n")

    return {
        "vocab_df": vocab_df,
        "command_df": command_df,
        "sentence_template_df": sentence_template_df,
        "sentence_instance_df": sentence_instance_df,
        "naming_df": naming_df,
        "command_id_df": command_id_df,
        "sentence_building_df": sentence_building_df,
    }


def transform_data(data):
    """Step 2: Transform and clean data."""
    logger.info("=" * 80)
    logger.info("STEP 2: Transforming and cleaning data")
    logger.info("=" * 80)

    for key, df in data.items():
        logger.info(f"Processing {key}...")

        # Trim whitespace from all string columns
        for col in df.columns:
            if df[col].dtype == "object":
                df[col] = df[col].str.strip()

        # Store back
        data[key] = df

    logger.info("✓ Data transformation complete\n")
    return data


def load_data(session: Session, data):
    """Step 3: Load data into database."""
    logger.info("=" * 80)
    logger.info("STEP 3: Loading data into database")
    logger.info("=" * 80)

    try:
        # Clear old data (in reverse order of insertion)
        logger.info("Clearing old data...")
        session.execute(delete(Exercise))
        session.execute(delete(SentenceInstanceAsset))
        session.execute(delete(CommandAsset))
        session.execute(delete(SentenceTemplateAsset))
        session.execute(delete(VocabularyAsset))
        session.flush()
        logger.info("✓ Old data cleared\n")

        # 1. Insert VocabularyAsset
        logger.info("Inserting vocabulary_assets...")
        vocab_id_map = {}
        vocab_obj_map = {}  # Keep objects for later reference
        for _, row in data["vocab_df"].iterrows():
            vocab_id = uuid_module.uuid4()
            vocab_id_map[row["vocab_id"]] = vocab_id

            accepted_answers = parse_comma_separated_string(row["accepted_answers"])
            image_file = convert_nan_to_none(row.get("image_file"))
            audio_file = convert_nan_to_none(row.get("audio_file"))

            topic_enum = Topic[TOPIC_MAP[row["topic"]]]
            word_type_enum = WordType[row["word_type"]]

            vocab = VocabularyAsset(
                id=vocab_id,
                canonical_word=row["canonical_word"],
                vocab_level=int(row["vocab_level"]),
                accepted_answers=accepted_answers,
                accepted_classifiers=None,
                image_file=image_file,
                audio_file=audio_file,
                topic=topic_enum,
                word_type=word_type_enum,
            )
            session.add(vocab)
            vocab_obj_map[row["vocab_id"]] = vocab

        session.flush()
        logger.info(f"✓ Inserted {len(vocab_id_map)} vocabulary_assets\n")

        # 2. Insert SentenceTemplateAsset
        logger.info("Inserting sentence_template_assets...")
        template_id_map = {}
        template_obj_map = {}  # Keep objects for later reference
        for _, row in data["sentence_template_df"].iterrows():
            template_id = uuid_module.uuid4()
            template_id_map[row["template_id"]] = template_id

            topic_enum = Topic[TOPIC_MAP[row["topic_constraint"]]]

            template = SentenceTemplateAsset(
                id=template_id,
                template=row["template"],
                topic_constraint=topic_enum,
            )
            session.add(template)
            template_obj_map[row["template_id"]] = template

        session.flush()
        logger.info(f"✓ Inserted {len(template_id_map)} sentence_template_assets\n")

        # 3. Insert CommandAsset
        logger.info("Inserting command_assets...")
        command_id_map = {}
        for _, row in data["command_df"].iterrows():
            command_id = uuid_module.uuid4()
            command_id_map[row["command_id"]] = command_id

            target_vocab_excel_id = row["target_vocab_id"]
            if target_vocab_excel_id not in vocab_id_map:
                raise ValueError(
                    f"Command {row['command_id']} references unknown vocab {target_vocab_excel_id}"
                )

            command_text = row.get("command_text", "")
            command_audio_file = convert_nan_to_none(row.get("command_audio_file"))
            # distractor_vocab_ids is NOT in Excel, always None during seed
            command = CommandAsset(
                id=command_id,
                command_text=command_text,
                command_audio_file=command_audio_file,
                target_vocab_id=vocab_id_map[target_vocab_excel_id],
                distractor_vocab_ids=None,
            )
            session.add(command)

        session.flush()
        logger.info(f"✓ Inserted {len(command_id_map)} command_assets\n")

        # 4. Insert SentenceInstanceAsset
        logger.info("Inserting sentence_instance_assets...")
        sentence_instance_id_map = {}
        sentence_instance_obj_map = {}  # Keep objects for later reference
        for _, row in data["sentence_instance_df"].iterrows():
            sentence_instance_id = uuid_module.uuid4()
            sentence_instance_id_map[row["sentence_instance_id"]] = sentence_instance_id

            template_excel_id = row["template_id"]
            vocab_excel_id = row["vocab_id"]

            if template_excel_id not in template_id_map:
                raise ValueError(
                    f"Sentence Instance {row['sentence_instance_id']} references unknown template {template_excel_id}"
                )
            if vocab_excel_id not in vocab_id_map:
                raise ValueError(
                    f"Sentence Instance {row['sentence_instance_id']} references unknown vocab {vocab_excel_id}"
                )

            accepted_answers = parse_comma_separated_string(row["accepted_answers"])
            sentence_audio_file = convert_nan_to_none(row.get("sentence_audio_file"))

            sentence_instance = SentenceInstanceAsset(
                id=sentence_instance_id,
                template_id=template_id_map[template_excel_id],
                vocab_id=vocab_id_map[vocab_excel_id],
                full_sentence=row["full_sentence"],
                accepted_answers=accepted_answers,
                audio_file=sentence_audio_file,
            )
            session.add(sentence_instance)
            sentence_instance_obj_map[row["sentence_instance_id"]] = sentence_instance

        session.flush()
        logger.info(f"✓ Inserted {len(sentence_instance_id_map)} sentence_instance_assets\n")

        # 5. Insert Exercise (naming)
        logger.info("Inserting exercises (naming)...")
        naming_count = 0
        for _, row in data["naming_df"].iterrows():
            vocab_excel_id = row["target_vocab_id"]
            if vocab_excel_id not in vocab_id_map:
                raise ValueError(
                    f"NAMING exercise {row['exercise_id']} references unknown vocab {vocab_excel_id}"
                )

            # Get topic and vocab_level from VocabularyAsset object
            vocab_obj = vocab_obj_map[vocab_excel_id]
            topic_enum = vocab_obj.topic
            vocab_level = vocab_obj.vocab_level

            exercise_type_enum = ExerciseType[row["exercise_type"]]
            suitable_profiles = parse_comma_separated_string(row["suitable_profiles"])

            exercise = Exercise(
                exercise_code=row["exercise_id"],
                exercise_type=exercise_type_enum,
                mode=None,
                topic=topic_enum,
                vocab_level=vocab_level,
                suitable_profiles=suitable_profiles,
                target_vocab_id=vocab_id_map[vocab_excel_id],
                target_command_id=None,
                target_sentence_instance_id=None,
                duration_expected=None,
            )
            session.add(exercise)
            naming_count += 1

        session.flush()
        logger.info(f"✓ Inserted {naming_count} exercises (naming)\n")

        # 6. Insert Exercise (command_identification)
        logger.info("Inserting exercises (command_identification)...")
        command_id_count = 0
        for _, row in data["command_id_df"].iterrows():
            vocab_excel_id = row["target_vocab_id"]
            if vocab_excel_id not in vocab_id_map:
                raise ValueError(
                    f"COMMAND IDENTIFICATION exercise {row['exercise_id']} references unknown vocab {vocab_excel_id}"
                )

            # Get topic and vocab_level from VocabularyAsset object
            vocab_obj = vocab_obj_map[vocab_excel_id]
            topic_enum = vocab_obj.topic
            vocab_level = vocab_obj.vocab_level

            exercise_type_enum = ExerciseType[row["exercise_type"]]
            mode_enum = CommandMode[row["mode"]]
            suitable_profiles = parse_comma_separated_string(row["suitable_profiles"])

            exercise = Exercise(
                exercise_code=row["exercise_id"],
                exercise_type=exercise_type_enum,
                mode=mode_enum,
                topic=topic_enum,
                vocab_level=vocab_level,
                suitable_profiles=suitable_profiles,
                target_vocab_id=vocab_id_map[vocab_excel_id],
                target_command_id=None,  # Always None per spec
                target_sentence_instance_id=None,
                duration_expected=None,
            )
            session.add(exercise)
            command_id_count += 1

        session.flush()
        logger.info(
            f"✓ Inserted {command_id_count} exercises (command_identification)\n"
        )

        # 7. Insert Exercise (sentence_building)
        logger.info("Inserting exercises (sentence_building)...")
        sentence_building_count = 0
        for _, row in data["sentence_building_df"].iterrows():
            sentence_instance_excel_id = row["target_sentence_instance_id"]
            if sentence_instance_excel_id not in sentence_instance_id_map:
                raise ValueError(
                    f"SENTENCE BUILDING exercise {row['exercise_id']} references unknown sentence instance {sentence_instance_excel_id}"
                )

            # Get topic and vocab_level from SentenceInstanceAsset -> VocabularyAsset
            # Need to get the vocab_id from sentence_instance, then get vocab_obj
            sentence_instance_vocab_excel_id = None
            for _, si_row in data["sentence_instance_df"].iterrows():
                if si_row["sentence_instance_id"] == sentence_instance_excel_id:
                    sentence_instance_vocab_excel_id = si_row["vocab_id"]
                    break

            if sentence_instance_vocab_excel_id is None:
                raise ValueError(
                    f"Cannot find vocab for sentence instance {sentence_instance_excel_id}"
                )

            vocab_obj = vocab_obj_map[sentence_instance_vocab_excel_id]
            topic_enum = vocab_obj.topic
            vocab_level = vocab_obj.vocab_level

            exercise_type_enum = ExerciseType[row["exercise_type"]]
            suitable_profiles = parse_comma_separated_string(row["suitable_profiles"])

            exercise = Exercise(
                exercise_code=row["exercise_id"],
                exercise_type=exercise_type_enum,
                mode=None,
                topic=topic_enum,
                vocab_level=vocab_level,
                suitable_profiles=suitable_profiles,
                target_vocab_id=None,
                target_command_id=None,
                target_sentence_instance_id=sentence_instance_id_map[
                    sentence_instance_excel_id
                ],
                duration_expected=None,
            )
            session.add(exercise)
            sentence_building_count += 1

        session.flush()
        logger.info(f"✓ Inserted {sentence_building_count} exercises (sentence_building)\n")

        # Commit all changes
        logger.info("Committing transaction...")
        session.commit()
        logger.info("✓ Transaction committed\n")

        return {
            "vocab_count": len(vocab_id_map),
            "template_count": len(template_id_map),
            "command_count": len(command_id_map),
            "sentence_instance_count": len(sentence_instance_id_map),
            "naming_count": naming_count,
            "command_id_count": command_id_count,
            "sentence_building_count": sentence_building_count,
        }

    except Exception as e:
        logger.error(f"Error during load: {e}")
        session.rollback()
        raise


def validate_data(session: Session, load_results):
    """Step 5: Validate loaded data."""
    logger.info("=" * 80)
    logger.info("STEP 5: Validating loaded data")
    logger.info("=" * 80)

    # Expected counts
    expected_counts = {
        "vocabulary_assets": 90,
        "sentence_template_assets": 10,
        "command_assets": 62,
        "sentence_instance_assets": 89,
        "exercises (naming)": 90,
        "exercises (command_identification)": 124,
        "exercises (sentence_building)": 89,
    }

    # Query actual counts
    vocab_count = session.query(VocabularyAsset).count()
    template_count = session.query(SentenceTemplateAsset).count()
    command_count = session.query(CommandAsset).count()
    sentence_instance_count = session.query(SentenceInstanceAsset).count()

    # Count exercises by type
    naming_count = (
        session.query(Exercise)
        .filter(Exercise.exercise_type == ExerciseType.naming)
        .count()
    )
    command_id_count = (
        session.query(Exercise)
        .filter(Exercise.exercise_type == ExerciseType.command_identification)
        .count()
    )
    sentence_building_count = (
        session.query(Exercise)
        .filter(Exercise.exercise_type == ExerciseType.sentence_building)
        .count()
    )

    actual_counts = {
        "vocabulary_assets": vocab_count,
        "sentence_template_assets": template_count,
        "command_assets": command_count,
        "sentence_instance_assets": sentence_instance_count,
        "exercises (naming)": naming_count,
        "exercises (command_identification)": command_id_count,
        "exercises (sentence_building)": sentence_building_count,
    }

    # Print validation results
    logger.info("Validation Results:")
    logger.info("=" * 80)
    all_match = True
    for table, expected in expected_counts.items():
        actual = actual_counts[table]
        match = "✓" if expected == actual else "✗ MISMATCH"
        logger.info(f"{table:45} Expected: {expected:3} | Actual: {actual:3} {match}")
        if expected != actual:
            all_match = False

    logger.info("=" * 80)
    if all_match:
        logger.info("✓ All counts match expected values!")
    else:
        logger.warning("✗ Some counts do NOT match expected values!")
        sys.exit(1)


def main():
    """Main ETL workflow."""
    logger.info("\n" + "=" * 80)
    logger.info("Starting ETL: Seed database from Excel files")
    logger.info("=" * 80 + "\n")

    args = parse_args()

    # Verify files exist
    asset_path = Path(args.asset_path)
    exercise_bank_path = Path(args.exercise_bank_path)

    if not asset_path.exists():
        logger.error(f"Asset file not found: {asset_path}")
        sys.exit(1)
    if not exercise_bank_path.exists():
        logger.error(f"Exercise bank file not found: {exercise_bank_path}")
        sys.exit(1)

    logger.info(f"Asset file: {asset_path}")
    logger.info(f"Exercise bank file: {exercise_bank_path}\n")

    # Step 1: Read and validate
    data = read_and_validate_raw_data(str(asset_path), str(exercise_bank_path))

    # Step 2: Transform
    data = transform_data(data)

    # Step 3: Load
    session = SessionLocal()
    try:
        load_results = load_data(session, data)

        # Step 5: Validate
        validate_data(session, load_results)
    finally:
        session.close()

    logger.info("\n" + "=" * 80)
    logger.info("✓ ETL completed successfully!")
    logger.info("=" * 80 + "\n")


if __name__ == "__main__":
    main()
