"""Daily balances and positions."""
from __future__ import annotations

import sqlite3
from typing import Any, Iterable

from ..db import now_iso


def record_balance(conn: sqlite3.Connection, account_id: str, as_of: str, balance: float,
                   available: float | None = None, source: str = "connector") -> None:
    """Upsert one balance for one day. Liabilities are stored as positive amounts owed."""
    conn.execute(
        "INSERT INTO balances_daily (account_id, as_of, balance, available, source, captured_at)"
        " VALUES (?,?,?,?,?,?)"
        " ON CONFLICT(account_id, as_of) DO UPDATE SET balance = excluded.balance,"
        " available = excluded.available, source = excluded.source, captured_at = excluded.captured_at",
        (account_id, as_of, float(balance), available, source, now_iso()))


def latest_balance(conn: sqlite3.Connection, account_id: str, on_or_before: str | None = None) -> tuple[str, float] | None:
    sql = "SELECT as_of, balance FROM balances_daily WHERE account_id = ?"
    params: list[Any] = [account_id]
    if on_or_before:
        sql += " AND as_of <= ?"
        params.append(on_or_before)
    r = conn.execute(sql + " ORDER BY as_of DESC LIMIT 1", params).fetchone()
    return (r["as_of"], r["balance"]) if r else None


def replace_positions(conn: sqlite3.Connection, account_id: str, as_of: str, rows: Iterable[dict[str, Any]],
                      source: str) -> int:
    """Replace the position set for an account on a day."""
    conn.execute("DELETE FROM positions WHERE account_id = ? AND as_of = ?", (account_id, as_of))
    n = 0
    ts = now_iso()
    for r in rows:
        key = r.get("symbol") or r.get("description") or "?"
        conn.execute(
            "INSERT OR REPLACE INTO positions (account_id, as_of, key, symbol, description, quantity, price,"
            " value, cost_basis, asset_class, source, captured_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (account_id, as_of, key, r.get("symbol"), r.get("description"), r.get("quantity"), r.get("price"),
             float(r.get("value") or 0), r.get("cost_basis"), r.get("asset_class"), source, ts))
        n += 1
    return n


def replace_defi(conn: sqlite3.Connection, account_id: str, as_of: str, rows: Iterable[dict[str, Any]]) -> int:
    conn.execute("DELETE FROM defi_positions WHERE account_id = ? AND as_of = ?", (account_id, as_of))
    n = 0
    ts = now_iso()
    for r in rows:
        conn.execute(
            "INSERT OR REPLACE INTO defi_positions (account_id, as_of, protocol, protocol_slug, network, meta_type,"
            " symbol, quantity, price, value, contract, captured_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (account_id, as_of, r["protocol"], r["protocol_slug"], r.get("network") or "", r["meta_type"],
             r["symbol"], r.get("quantity"), r.get("price"), abs(float(r.get("value") or 0)),
             r.get("contract") or "", ts))
        n += 1
    return n


def positions_value(conn: sqlite3.Connection, account_id: str, on_or_before: str | None = None) -> float | None:
    sql = "SELECT as_of FROM positions WHERE account_id = ?"
    params: list[Any] = [account_id]
    if on_or_before:
        sql += " AND as_of <= ?"
        params.append(on_or_before)
    r = conn.execute(sql + " ORDER BY as_of DESC LIMIT 1", params).fetchone()
    if not r:
        return None
    v = conn.execute("SELECT SUM(value) FROM positions WHERE account_id = ? AND as_of = ?",
                     (account_id, r["as_of"])).fetchone()[0]
    return float(v or 0)
