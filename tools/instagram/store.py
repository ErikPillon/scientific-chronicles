"""SQLite-backed queue for candidate posts and their approval state."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    mmdd          TEXT NOT NULL,
    source_kind   TEXT NOT NULL,
    source_path   TEXT NOT NULL,
    title         TEXT NOT NULL,
    caption       TEXT NOT NULL,
    image_path    TEXT NOT NULL,
    image_origin  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    tg_chat_id    TEXT,
    tg_message_id INTEGER,
    scheduled_for TEXT,
    r2_key        TEXT,
    r2_url        TEXT,
    ig_media_id   TEXT,
    ig_permalink  TEXT,
    error         TEXT,
    published_at  TEXT,
    target_date   TEXT,
    meta          TEXT
);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_source ON posts(source_path);
CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_tg_msg
    ON posts(tg_chat_id, tg_message_id) WHERE tg_message_id IS NOT NULL;
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a database was first created."""
    have = {row["name"] for row in conn.execute("PRAGMA table_info(posts)")}
    if "target_date" not in have:
        conn.execute("ALTER TABLE posts ADD COLUMN target_date TEXT")
        # Existing rows were same-day by definition.
        conn.execute("UPDATE posts SET target_date = substr(created_at, 1, 10) "
                     "WHERE target_date IS NULL")
        conn.commit()


def recently_posted(conn: sqlite3.Connection) -> set[str]:
    """Source paths that are published, queued, or too recent to repeat."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=config.REPOST_COOLDOWN_DAYS)).isoformat()
    rows = conn.execute(
        """
        SELECT DISTINCT source_path FROM posts
         WHERE status IN ('pending', 'approved', 'published')
           AND created_at >= ?
        """,
        (cutoff,),
    ).fetchall()
    return {row["source_path"] for row in rows}


def add_post(conn: sqlite3.Connection, **fields: Any) -> int:
    fields.setdefault("created_at", now())
    if isinstance(fields.get("meta"), dict):
        fields["meta"] = json.dumps(fields["meta"])
    columns = ", ".join(fields)
    placeholders = ", ".join("?" for _ in fields)
    cursor = conn.execute(
        f"INSERT INTO posts ({columns}) VALUES ({placeholders})", tuple(fields.values())
    )
    conn.commit()
    return int(cursor.lastrowid)


def update(conn: sqlite3.Connection, post_id: int, **fields: Any) -> None:
    assignments = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(
        f"UPDATE posts SET {assignments} WHERE id = ?", (*fields.values(), post_id)
    )
    conn.commit()


def media_path(stored: str):
    """Resolve a stored image reference to a local file.

    Rows written before this was relative hold the absolute path of whichever
    machine rendered them, so fall back to the basename under this host's
    media directory.
    """
    from pathlib import Path
    if not stored:
        return None
    candidate = Path(stored)
    if candidate.is_absolute() and candidate.is_file():
        return candidate
    return config.MEDIA_DIR / candidate.name


def get_post(conn: sqlite3.Connection, post_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()


def by_telegram_message(conn: sqlite3.Connection, chat_id: str, message_id: int):
    return conn.execute(
        "SELECT * FROM posts WHERE tg_chat_id = ? AND tg_message_id = ?",
        (str(chat_id), message_id),
    ).fetchone()


def due_for_publish(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Approved posts whose scheduled time has arrived."""
    return conn.execute(
        """
        SELECT * FROM posts
         WHERE status = 'approved'
           AND (scheduled_for IS NULL OR scheduled_for <= ?)
         ORDER BY id
        """,
        (now(),),
    ).fetchall()


def published_last_24h(conn: sqlite3.Connection) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM posts WHERE status = 'published' AND published_at >= ?",
        (cutoff,),
    ).fetchone()
    return int(row["n"])


def published_on(conn: sqlite3.Connection, day) -> int:
    """Posts published for a given target date.

    Counting by target date rather than a rolling window keeps a staggered
    run of same-day posts from starving itself against the daily ceiling.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM posts WHERE status = 'published' AND target_date = ?",
        (day.isoformat(),),
    ).fetchone()
    return int(row["n"])


def slots_taken(conn: sqlite3.Connection, day) -> int:
    """Posts already holding a publishing slot on a target day."""
    row = conn.execute(
        """SELECT COUNT(*) AS n FROM posts
            WHERE target_date = ? AND status IN ('approved', 'published')""",
        (day.isoformat(),),
    ).fetchone()
    return int(row["n"])


def queued_for(conn: sqlite3.Connection, day) -> list[sqlite3.Row]:
    """Everything already prepared for a target date, in slot order."""
    return conn.execute(
        """SELECT * FROM posts
            WHERE target_date = ? AND status IN ('pending', 'approved', 'published')
            ORDER BY id""",
        (day.isoformat(),),
    ).fetchall()


def offered_for(conn: sqlite3.Connection, day) -> list[sqlite3.Row]:
    """Everything ever offered for a target day, whatever its status."""
    return conn.execute(
        "SELECT * FROM posts WHERE target_date = ? ORDER BY id", (day.isoformat(),)
    ).fetchall()
