
import os
import sqlite3
from flask import g


def get_db(app=None):
    if "db" not in g:
        if app is None:
            from flask import current_app
            app = current_app

        db_path = os.path.join(
            app.instance_path,
            "papergraph.db"
        )

        os.makedirs(app.instance_path, exist_ok=True)

        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")

    return g.db


def close_db(error=None):
    db = g.pop("db", None)

    if db is not None:
        db.close()


def init_db(app):
    os.makedirs(app.instance_path, exist_ok=True)

    db_path = os.path.join(
        app.instance_path,
        "papergraph.db"
    )

    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")

    connection.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS papers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
            ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        paper_id INTEGER,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
            ON DELETE CASCADE,
        FOREIGN KEY (paper_id) REFERENCES papers(id)
            ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS summary_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        paper_id INTEGER,
        summary TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
            ON DELETE CASCADE,
        FOREIGN KEY (paper_id) REFERENCES papers(id)
            ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS comparison_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        paper_a_id INTEGER,
        paper_b_id INTEGER,
        aspect TEXT,
        result TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
            ON DELETE CASCADE,
        FOREIGN KEY (paper_a_id) REFERENCES papers(id)
            ON DELETE SET NULL,
        FOREIGN KEY (paper_b_id) REFERENCES papers(id)
            ON DELETE SET NULL
    );
    """)
    # Add Neo4j paper ID column to existing databases
    columns = [
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(papers)"
        ).fetchall()
    ]

    if "neo4j_id" not in columns:
        connection.execute(
            "ALTER TABLE papers ADD COLUMN neo4j_id TEXT"
        )
    connection.commit()
    connection.close()


def init_app(app):
    app.teardown_appcontext(close_db)
