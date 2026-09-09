from __future__ import annotations

import json
import sqlite3
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from ..config import Config
from ..db import now_iso


@dataclass
class SyncResult:
    connector: str
    ok: bool = True
    rows_written: int = 0
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    skipped: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"connector": self.connector, "ok": self.ok, "rows_written": self.rows_written,
                "detail": self.detail, "error": self.error, "skipped": self.skipped}


class Connector(Protocol):
    name: str

    def configured(self) -> bool: ...

    def sync(self, conn: sqlite3.Connection, cfg: Config, as_of: str) -> SyncResult: ...


def store_raw(conn: sqlite3.Connection, connector: str, kind: str, ref: str | None, payload: Any) -> None:
    conn.execute("INSERT INTO raw_sync (connector, kind, ref, fetched_at, payload) VALUES (?,?,?,?,?)",
                 (connector, kind, ref, now_iso(), json.dumps(payload, default=str, separators=(",", ":"))))


def prune_raw(conn: sqlite3.Connection, keep_days: int = 60) -> int:
    cur = conn.execute("DELETE FROM raw_sync WHERE fetched_at < datetime('now', ?)", (f"-{int(keep_days)} days",))
    return cur.rowcount


def mark_started(conn: sqlite3.Connection, name: str) -> str:
    ts = now_iso()
    conn.execute("INSERT INTO connector_health (connector, status, last_started_at) VALUES (?, 'running', ?)"
                 " ON CONFLICT(connector) DO UPDATE SET status = 'running', last_started_at = excluded.last_started_at",
                 (name, ts))
    return ts


def record_result(conn: sqlite3.Connection, result: SyncResult) -> None:
    ts = now_iso()
    if result.skipped:
        conn.execute("UPDATE connector_health SET status = CASE WHEN last_success_at IS NULL THEN 'never' ELSE 'ok' END"
                     " WHERE connector = ?", (result.connector,))
        return
    if result.ok:
        conn.execute("INSERT INTO connector_health (connector, status, last_success_at, rows_written, detail)"
                     " VALUES (?, 'ok', ?, ?, ?) ON CONFLICT(connector) DO UPDATE SET status='ok',"
                     " last_success_at=excluded.last_success_at, rows_written=excluded.rows_written,"
                     " detail=excluded.detail, last_error=NULL",
                     (result.connector, ts, result.rows_written, json.dumps(result.detail, default=str)))
    else:
        conn.execute("INSERT INTO connector_health (connector, status, last_error_at, last_error, detail)"
                     " VALUES (?, 'error', ?, ?, ?) ON CONFLICT(connector) DO UPDATE SET status='error',"
                     " last_error_at=excluded.last_error_at, last_error=excluded.last_error, detail=excluded.detail",
                     (result.connector, ts, (result.error or "")[:2000], json.dumps(result.detail, default=str)))


def run_connector(connector: Connector, conn: sqlite3.Connection, cfg: Config, as_of: str) -> SyncResult:
    """Run one connector inside a transaction with health bookkeeping."""
    mark_started(conn, connector.name)
    conn.execute("BEGIN")
    try:
        result = connector.sync(conn, cfg, as_of)
        conn.execute("COMMIT")
    except Exception as e:  # noqa: BLE001
        conn.execute("ROLLBACK")
        result = SyncResult(connector.name, ok=False, error=f"{type(e).__name__}: {e}",
                            detail={"trace": traceback.format_exc()[-1500:]})
    record_result(conn, result)
    return result


def parse_kv_conf(path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return out


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
