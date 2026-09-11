"""Goals: config-defined, synced into the goals table, progress from linked accounts."""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any

from ..config import Config
from ..db import now_iso


def _resolve_accounts(conn: sqlite3.Connection, refs: list[str]) -> list[str]:
    ids = []
    for ref in refs:
        row = conn.execute("SELECT id FROM accounts WHERE id = ?", (ref,)).fetchone()
        if row:
            ids.append(row["id"])
            continue
        for r in conn.execute("SELECT id FROM accounts WHERE is_active = 1 AND lower(name) LIKE ?", (f"%{ref.lower()}%",)):
            ids.append(r["id"])
    return sorted(set(ids))


def sync_goals(conn: sqlite3.Connection, cfg: Config) -> int:
    n = 0
    for g in cfg.goals:
        ids = _resolve_accounts(conn, g.linked_accounts)
        conn.execute(
            "INSERT INTO goals (slug, name, kind, target_amount, target_date, start_amount, current_amount, linked_account_ids,"
            " monthly_contribution, priority, notes, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(slug) DO UPDATE SET name=excluded.name, kind=excluded.kind, target_amount=excluded.target_amount,"
            " target_date=excluded.target_date, start_amount=COALESCE(excluded.start_amount, goals.start_amount),"
            " current_amount=excluded.current_amount, linked_account_ids=excluded.linked_account_ids,"
            " monthly_contribution=excluded.monthly_contribution, priority=excluded.priority, notes=excluded.notes,"
            " updated_at=excluded.updated_at",
            (g.slug, g.name, g.kind, g.target_amount, g.target_date, g.start_amount, g.current_amount, json.dumps(ids),
             g.monthly_contribution, g.priority, g.notes, now_iso()))
        n += 1
    return n


def _balance(conn: sqlite3.Connection, aid: str) -> float:
    b = conn.execute("SELECT balance FROM balances_daily WHERE account_id = ? ORDER BY as_of DESC LIMIT 1", (aid,)).fetchone()
    if b and abs(b["balance"]) > 0.005:
        return float(b["balance"])
    p = conn.execute("SELECT SUM(value) FROM positions_latest WHERE account_id = ?", (aid,)).fetchone()[0]
    return float(p or 0)


def progress(conn: sqlite3.Connection, today: date | None = None) -> list[dict[str, Any]]:
    today = today or date.today()
    out = []
    for g in conn.execute("SELECT * FROM goals ORDER BY priority, target_date"):
        ids = json.loads(g["linked_account_ids"] or "[]")
        linked = round(sum(_balance(conn, a) for a in ids), 2) if ids else None
        current = linked if linked is not None else (g["current_amount"] or 0.0)
        target = g["target_amount"]
        months_left = None
        if g["target_date"]:
            td = date.fromisoformat(g["target_date"][:10])
            months_left = max((td.year - today.year) * 12 + td.month - today.month, 0)
        if g["kind"] == "debt":
            start = g["start_amount"] or current
            paid = max(start - current, 0)
            pct = round(paid / start, 3) if start else None
            remaining = current
        else:
            pct = round(current / target, 3) if target else None
            remaining = round((target or 0) - current, 2)
        needed = round(remaining / months_left, 2) if months_left and remaining and remaining > 0 else None
        out.append({"slug": g["slug"], "name": g["name"], "kind": g["kind"], "priority": g["priority"],
                    "target_amount": target, "target_date": g["target_date"], "current": round(current, 2),
                    "start_amount": g["start_amount"],
                    "linked_accounts": ids, "pct": pct, "remaining": remaining, "months_left": months_left,
                    "needed_monthly": needed, "monthly_contribution": g["monthly_contribution"],
                    "on_track": (needed is None or (g["monthly_contribution"] or 0) >= needed) if pct is not None else None,
                    "notes": g["notes"]})
    return out
