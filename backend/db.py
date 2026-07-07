"""SQLite cache for pulled ESPN data.

Everything is stored as a JSON blob keyed by data type (roster, standings,
matchups, transactions), plus when it was last synced. Simple key/value
caching is enough for Phase 1 - no need for a normalized schema yet.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "cache.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def set_cache(key: str, data) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO cache (key, data, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at
        """,
        (key, json.dumps(data), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def get_cache(key: str):
    conn = get_connection()
    row = conn.execute("SELECT data, updated_at FROM cache WHERE key = ?", (key,)).fetchone()
    conn.close()
    if row is None:
        return None
    return {"data": json.loads(row["data"]), "updated_at": row["updated_at"]}


def all_cache_status() -> dict:
    conn = get_connection()
    rows = conn.execute("SELECT key, updated_at FROM cache").fetchall()
    conn.close()
    return {row["key"]: row["updated_at"] for row in rows}
