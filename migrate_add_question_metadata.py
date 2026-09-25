"""
One-time migration: adds the richer question-metadata columns
(difficulty, topic, tags, explanations) to banked_question.
Works on both SQLite (local dev) and Postgres (Render/Supabase production).
Run this ONCE against each database, then delete or archive this file.
"""

from app import create_app
from extensions import db
from sqlalchemy import text, inspect

app = create_app()

# Column name -> SQL type to use in ALTER TABLE
NEW_COLUMNS = {
    "difficulty": "VARCHAR(20)",
    "core_topic": "VARCHAR(120)",
    "sub_concept": "VARCHAR(150)",
    "question_format": "VARCHAR(60)",
    "tags_json": "TEXT",
    "overall_explanation": "TEXT",
    "distractor_explanations_json": "TEXT",
    "external_id": "VARCHAR(60)",
}

with app.app_context():
    inspector = inspect(db.engine)
    existing_columns = {col["name"] for col in inspector.get_columns("banked_question")}

    with db.engine.connect() as conn:
        for col_name, col_type in NEW_COLUMNS.items():
            if col_name in existing_columns:
                print(f"Skipping '{col_name}' — already exists.")
                continue

            stmt = f'ALTER TABLE banked_question ADD COLUMN {col_name} {col_type};'
            print(f"Running: {stmt}")
            conn.execute(text(stmt))
            conn.commit()

    print("Migration complete.")
