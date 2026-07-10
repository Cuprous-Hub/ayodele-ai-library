"""
One-time migration: adds the new columns needed for class promotion.
Works on both SQLite (local dev) and Postgres (Supabase production).
Run this ONCE against each database, then delete or archive this file.
"""

from app import create_app
from extensions import db
from sqlalchemy import text, inspect

app = create_app()

# Column name -> SQL type to use in ALTER TABLE
NEW_COLUMNS = {
    "level_history": "TEXT",
    "is_repeating": "BOOLEAN DEFAULT 0",
    "is_class_teacher": "BOOLEAN DEFAULT 0",
    "assigned_level": "VARCHAR(10)",
}

with app.app_context():
    inspector = inspect(db.engine)
    existing_columns = {col["name"] for col in inspector.get_columns("user")}

    with db.engine.connect() as conn:
        for col_name, col_type in NEW_COLUMNS.items():
            if col_name in existing_columns:
                print(f"Skipping '{col_name}' — already exists.")
                continue

            stmt = f'ALTER TABLE "user" ADD COLUMN {col_name} {col_type};'
            print(f"Running: {stmt}")
            conn.execute(text(stmt))
            conn.commit()

    print("Migration complete.")