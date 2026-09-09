"""Daily net-worth snapshots computed from balances and positions."""
from __future__ import annotations

import json
import sqlite3
from datetime import date

from ..config import KIND_CLASS
from ..db import now_iso
from .balances import latest_balance, positions_value


def account_value(conn: sqlite3.Connection, account: sqlite3.Row | dict, as_of: str) -> tuple[float | None, str]:
    """Best value for an account on a day.

    A connector-reported balance is the authoritative total (it includes cash,
    DeFi equity, NFTs). Positions are the itemised detail and are used when no
    balance exists, when the balance is stale relative to the positions, or when
    the provider reported a zero balance for an account that clearly holds
    positions (Fina does this for some workplace plans).
    """
    aid = account["id"]
    bal = latest_balance(conn, aid, as_of)
    pv = positions_value(conn, aid, as_of)
    if pv is not None:
        pos_as_of = conn.execute("SELECT MAX(as_of) FROM positions WHERE account_id = ? AND as_of <= ?",
                                 (aid, as_of)).fetchone()[0]
        defi = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN meta_type = 'BORROWED' THEN -value ELSE value END), 0)"
            " FROM defi_positions WHERE account_id = ? AND as_of = ?", (aid, pos_as_of)).fetchone()[0]
        pv = float(pv) + float(defi or 0)
    if bal and pv is not None:
        pos_as_of = conn.execute("SELECT MAX(as_of) FROM positions WHERE account_id = ? AND as_of <= ?",
                                 (aid, as_of)).fetchone()[0]
        if bal[0] >= (pos_as_of or "") and abs(bal[1]) > 0.005:
            return bal[1], "balance"
        return pv, "positions"
    if bal:
        return bal[1], "balance"
    if pv is not None:
        return pv, "positions"
    return None, "none"


def snapshot_day(conn: sqlite3.Connection, as_of: str | None = None) -> dict:
    as_of = as_of or date.today().isoformat()
    accounts = conn.execute("SELECT * FROM accounts WHERE is_active = 1").fetchall()
    assets = liabilities = 0.0
    by_class: dict[str, float] = {}
    by_entity: dict[str, float] = {}
    detail = []
    for a in accounts:
        value, how = account_value(conn, a, as_of)
        if value is None:
            continue
        value = float(value)
        cls = KIND_CLASS.get(a["kind"], "other")
        if a["is_liability"]:
            liabilities += abs(value)
            by_class[cls] = by_class.get(cls, 0.0) - abs(value)
            by_entity[a["entity"]] = by_entity.get(a["entity"], 0.0) - abs(value)
        else:
            assets += value
            by_class[cls] = by_class.get(cls, 0.0) + value
            by_entity[a["entity"]] = by_entity.get(a["entity"], 0.0) + value
        detail.append({"id": a["id"], "name": a["name"], "kind": a["kind"], "value": round(value, 2), "via": how})
    net = assets - liabilities
    conn.execute(
        "INSERT INTO snapshots_daily (as_of, assets, liabilities, net_worth, by_class, by_entity, captured_at)"
        " VALUES (?,?,?,?,?,?,?) ON CONFLICT(as_of) DO UPDATE SET assets=excluded.assets,"
        " liabilities=excluded.liabilities, net_worth=excluded.net_worth, by_class=excluded.by_class,"
        " by_entity=excluded.by_entity, captured_at=excluded.captured_at",
        (as_of, round(assets, 2), round(liabilities, 2), round(net, 2),
         json.dumps({k: round(v, 2) for k, v in by_class.items()}),
         json.dumps({k: round(v, 2) for k, v in by_entity.items()}), now_iso()))
    return {"as_of": as_of, "assets": round(assets, 2), "liabilities": round(liabilities, 2),
            "net_worth": round(net, 2), "by_class": by_class, "by_entity": by_entity, "accounts": detail}


def series(conn: sqlite3.Connection, days: int = 365) -> list[dict]:
    rows = conn.execute("SELECT as_of, assets, liabilities, net_worth, by_class FROM snapshots_daily"
                        " WHERE as_of >= date('now', ?) ORDER BY as_of", (f"-{int(days)} days",)).fetchall()
    return [{"as_of": r["as_of"], "assets": r["assets"], "liabilities": r["liabilities"],
             "net_worth": r["net_worth"], "by_class": json.loads(r["by_class"])} for r in rows]
