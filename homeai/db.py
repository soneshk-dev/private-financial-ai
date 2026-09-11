"""SQLite connection helpers and a tiny numbered-SQL migration runner."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30, isolation_level=None, check_same_thread=False)  # autocommit; one connection per request, may cross threadpool threads
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _available_migrations() -> list[tuple[int, str, Path]]:
    out = []
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        m = re.match(r"(\d+)_(.+)\.sql$", p.name)
        if m:
            out.append((int(m.group(1)), m.group(2), p))
    return out


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply any unapplied migrations in order. Returns the versions applied."""
    done = applied_versions(conn)
    applied = []
    for version, name, path in _available_migrations():
        if version in done:
            continue
        sql = path.read_text()
        # executescript() commits any open transaction first, so the BEGIN/COMMIT
        # must live inside the script itself for the migration to be atomic.
        try:
            conn.executescript("BEGIN;\n" + sql + "\nCOMMIT;")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        conn.execute("INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                     (version, name, now_iso()))
        applied.append(version)
    return applied


def transaction(conn: sqlite3.Connection):
    """Context manager: BEGIN ... COMMIT/ROLLBACK."""
    class _Tx:
        def __enter__(self):
            conn.execute("BEGIN")
            return conn

        def __exit__(self, exc_type, exc, tb):
            conn.execute("ROLLBACK" if exc_type else "COMMIT")
            return False
    return _Tx()
