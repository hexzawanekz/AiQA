"""SQLite database layer for Auto-Report2. Same schema as Node.js Auto-Report."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

# Auto-Report2 standalone: use own data directory
_BASE = Path(__file__).resolve().parent
_REPORTS_BASE = _BASE / "data"
DB_PATH = _REPORTS_BASE / "database" / "test-results.db"


def _ensure_db_path() -> Path:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return DB_PATH


@contextmanager
def get_connection(db_path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for database connections."""
    path = db_path or _ensure_db_path()
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_schema(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist. Matches Node.js schema."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            project_url TEXT NOT NULL,
            project_password TEXT,
            project_story TEXT,
            environment TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS test_case_uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            file_type TEXT,
            size INTEGER,
            content TEXT NOT NULL,
            uploaded_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS test_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upload_id INTEGER NOT NULL REFERENCES test_case_uploads(id) ON DELETE CASCADE,
            tc_id TEXT NOT NULL,
            title TEXT NOT NULL,
            module TEXT,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS project_testcases (
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            test_case_id INTEGER NOT NULL REFERENCES test_case_uploads(id) ON DELETE CASCADE,
            PRIMARY KEY (project_id, test_case_id)
        );

        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER,
            row INTEGER,
            case_name TEXT,
            param TEXT,
            status TEXT,
            error TEXT,
            duration TEXT,
            screenshot TEXT,
            video TEXT,
            module TEXT,
            environment TEXT,
            app TEXT,
            timestamp TEXT
        );

        CREATE TABLE IF NOT EXISTS reports_summary (
            run_id INTEGER PRIMARY KEY,
            passed INTEGER,
            failed INTEGER,
            skipped INTEGER,
            total INTEGER,
            environment TEXT,
            app TEXT,
            executedAt TEXT,
            executionTime TEXT
        );
    """)
    # Optional column (ignore if exists)
    try:
        conn.execute("ALTER TABLE reports_summary ADD COLUMN project_id INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE test_cases ADD COLUMN module TEXT")
    except sqlite3.OperationalError:
        pass


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert sqlite3.Row to dict."""
    return dict(row) if row else {}
