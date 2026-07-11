"""
One-time migration: adds the new columns needed for class promotion.
Works on both SQLite (local dev) and Postgres (Render/Supabase production).
Run this ONCE against each database, then delete or archive this file.
"""

from app import create_app
from extensions import db
from sqlalchemy import text, inspect

app = create_app()

# Column name -> SQL type to use in ALTER TABLE
# Note: TRUE/FALSE (not 0/1) so this works correctly on Postgres, not just SQLite.
NEW_COLUMNS = {
    "level_history": "TEXT",
    "is_repeating": "BOOLEAN DEFAULT FALSE",
    "is_class_teacher": "BOOLEAN DEFAULT FALSE",
    "assigned_level": "VARCHAR(10)",
    "email_verified": "BOOLEAN DEFAULT FALSE",
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