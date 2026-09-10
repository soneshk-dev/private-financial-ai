from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..config import KIND_CLASS
from ..ledger.accounts import list_accounts
from ..ledger.snapshots import series, snapshot_day


def net_worth(conn: sqlite3.Connection, days: int = 365) -> dict[str, Any]:
    latest = conn.execute("SELECT * FROM snapshots_daily ORDER BY as_of DESC LIMIT 1").fetchone()
    if latest is None:
        # First run: snapshot at the latest date we have data for (never earlier than today's data).
        as_of = conn.execute("SELECT MAX(d) FROM (SELECT MAX(as_of) d FROM balances_daily UNION ALL"
                             " SELECT MAX(as_of) FROM positions UNION ALL SELECT date('now'))").fetchone()[0]
        conn.execute("BEGIN")
        snapshot_day(conn, as_of)
        conn.execute("COMMIT")
        latest = conn.execute("SELECT * FROM snapshots_daily ORDER BY as_of DESC LIMIT 1").fetchone()
    accounts = list_accounts(conn)
    by_class: dict[str, list[dict]] = {}
    for a in accounts:
        by_class.setdefault(a["asset_class"], []).append(
            {"id": a["id"], "name": a["name"], "institution": a["institution"], "kind": a["kind"],
             "entity": a["entity"], "balance": a["latest_balance"], "as_of": a["balance_as_of"]})
    s = series(conn, days)
    first = s[0]["net_worth"] if s else None
    return {
        "as_of": latest["as_of"], "assets": latest["assets"], "liabilities": latest["liabilities"],
        "net_worth": latest["net_worth"], "by_class": json.loads(latest["by_class"]),
        "by_entity": json.loads(latest["by_entity"]),
        "change": (round(latest["net_worth"] - first, 2) if first is not None else None),
        "series": s, "accounts_by_class": by_class,
    }


def accounts_summary(conn: sqlite3.Connection, active_only: bool = True) -> list[dict[str, Any]]:
    return list_accounts(conn, active_only=active_only)


def class_of(kind: str) -> str:
    return KIND_CLASS.get(kind, "other")
