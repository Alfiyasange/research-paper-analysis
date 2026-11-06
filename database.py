
import os
import sqlite3
from flask import g

import socket
from urllib.parse import urlparse
class PostgresConnection:
    """Compatibility wrapper for existing SQLite-style queries."""

    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=()):
        sql = sql.replace("?", "%s")
        return self.connection.execute(sql, params)

    def commit(self):
        self.connection.commit()

    def close(self):
        self.connection.close()


def get_database_url():
    url = os.environ.get("DATABASE_URL", "").strip()

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    return url


def get_db(app=None):
    if "db" not in g:
        database_url = get_database_url()

        if database_url:
            import psycopg
            from psycopg.rows import dict_row
            parsed = urlparse(database_url)
            host = parsed.hostname
            port = parsed.port or 5432

            print("DB diagnostic host:", host, "port:", port, flush=True)

            try:
                test_socket = socket.create_connection(
                    (host, port), timeout=8
                )
                test_socket.close()
                print("DB TCP diagnostic: SUCCESS", flush=True)
            except Exception as exc:
                print(
                    "DB TCP diagnostic FAILED:",
                    type(exc).__name__,
                    str(exc),
                    flush=True
                )

            connection = psycopg.connect(
                database_url,
                row_factory=dict_row,
                connect_timeout=15
            )
            g.db = PostgresConnection(connection)

        else:
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
    database_url = get_database_url()

    if database_url:
        import psycopg
        from psycopg.rows import dict_row

        connection = psycopg.connect(
            database_url,
            row_factory=dict_row,
            connect_timeout=15
        )

        try:
            schema = [
                """
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS papers (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id)
                        ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    neo4j_id TEXT
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS chat_history (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id)
                        ON DELETE CASCADE,
                    paper_id BIGINT REFERENCES papers(id)
                        ON DELETE SET NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS summary_history (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id)
                        ON DELETE CASCADE,
                    paper_id BIGINT REFERENCES papers(id)
                        ON DELETE SET NULL,
                    summary TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS comparison_history (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id)
                        ON DELETE CASCADE,
                    paper_a_id BIGINT REFERENCES papers(id)
                        ON DELETE SET NULL,
                    paper_b_id BIGINT REFERENCES papers(id)
                        ON DELETE SET NULL,
                    aspect TEXT,
                    result TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """,
                """
                ALTER TABLE papers
                ADD COLUMN IF NOT EXISTS neo4j_id TEXT
                """
            ]

            for statement in schema:
                connection.execute(statement)

            connection.commit()

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    else:
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
