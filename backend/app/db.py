import sqlite3
from contextlib import contextmanager

from app.config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    source_lang TEXT NOT NULL,
    page_count INTEGER,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL REFERENCES books(id),
    job_type TEXT NOT NULL DEFAULT 'translate',
    status TEXT NOT NULL,
    current_stage TEXT,
    total_chunks INTEGER,
    completed_chunks INTEGER DEFAULT 0,
    failed_chunks INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        # Migration for DBs created before job_type existed.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        if "job_type" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN job_type TEXT NOT NULL DEFAULT 'translate'")
        # Jobs can't survive a process restart — mark any leftovers as interrupted.
        conn.execute(
            "UPDATE jobs SET status = 'error', error_message = 'Interrupted by server restart'"
            " WHERE status IN ('queued', 'running')"
        )


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def update_book(book_id: str, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    with get_connection() as conn:
        conn.execute(f"UPDATE books SET {sets} WHERE id = ?", (*fields.values(), book_id))


def update_job(job_id: str, **fields) -> None:
    from datetime import datetime, timezone

    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    sets = ", ".join(f"{k} = ?" for k in fields)
    with get_connection() as conn:
        conn.execute(f"UPDATE jobs SET {sets} WHERE id = ?", (*fields.values(), job_id))


def get_job(job_id: str):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def get_latest_job_for_book(book_id: str):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM jobs WHERE book_id = ? ORDER BY created_at DESC LIMIT 1", (book_id,)
        ).fetchone()
