import os
import uuid
import shutil

import app
import core
import database

USER_ID = 1
SOURCE_DIR = "papers"
UPLOAD_DIR = os.path.join("uploads", str(USER_ID))

os.makedirs(UPLOAD_DIR, exist_ok=True)

print("Starting PaperGraph import...")
core.setup()

with app.app.app_context():
    db = database.get_db()

    pdf_files = [
        f for f in os.listdir(SOURCE_DIR)
        if f.lower().endswith(".pdf")
    ]

    imported = 0
    skipped = 0
    failed = 0

    for filename in pdf_files:
        existing = db.execute(
            "SELECT id FROM papers WHERE user_id = ? AND filename = ?",
            (USER_ID, filename)
        ).fetchone()

        if existing:
            print(f"SKIPPED: {filename} (already imported)")
            skipped += 1
            continue

        source_path = os.path.join(SOURCE_DIR, filename)
        unique_name = str(uuid.uuid4()) + "_" + filename
        destination = os.path.join(UPLOAD_DIR, unique_name)

        try:
            shutil.copy2(source_path, destination)

            result = core.ingest(destination, filename, USER_ID)

            db.execute(
                """
                INSERT INTO papers
                (user_id, title, filename, file_path, neo4j_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    USER_ID,
                    result["title"],
                    filename,
                    destination,
                    result["id"]
                )
            )
            db.commit()

            imported += 1
            print(f"IMPORTED: {filename}")

        except Exception as error:
            db.rollback()
            failed += 1
            print(f"FAILED: {filename} — {error}")

    print("\nImport completed!")
    print("Imported:", imported)
    print("Skipped:", skipped)
    print("Failed:", failed)