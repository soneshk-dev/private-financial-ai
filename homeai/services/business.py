"""Entities (personal / businesses), per-entity P&L, and a review queue of
transactions that look like business activity sitting on personal accounts."""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from ..config import Config
from ..db import now_iso
from ..ledger.classify import INCOME_FLOWS, SPENDING_FLOWS

_INC = ",".join(f"'{f}'" for f in INCOME_FLOWS)
_SP = ",".join(f"'{f}'" for f in SPENDING_FLOWS)
INTERNAL = re.compile(r"CORE ACCOUNT|SWEEP|REINVEST|FDIC|withdrawal|FIDELITY|VANGUARD|MMKT|MONEY MARKET", re.I)
BUSINESSY = re.compile(r"business|consult|legal|software|saas|design|domain|hosting|cloud|advertis|marketing|"
                       r"payroll|contractor|invoice|llc|inc\b", re.I)


def sync_entities(conn: sqlite3.Connection, cfg: Config) -> int:
    n = 0
    for e in cfg.entities:
        conn.execute("INSERT INTO entities (slug, name, kind, tax_form, notes, updated_at) VALUES (?,?,?,?,?,?)"
                     " ON CONFLICT(slug) DO UPDATE SET name=excluded.name, kind=excluded.kind, tax_form=excluded.tax_form,"
                     " notes=excluded.notes, updated_at=excluded.updated_at",
                     (e.slug, e.name, e.kind, e.tax_form, e.notes, now_iso()))
        n += 1
    return n


def list_entities(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT e.*, (SELECT COUNT(*) FROM accounts a WHERE a.entity = e.slug AND a.is_active = 1) AS accounts,"
                        " (SELECT COUNT(*) FROM transactions_v t WHERE t.entity = e.slug) AS transactions"
                        " FROM entities e WHERE is_active = 1 ORDER BY kind = 'personal' DESC, name").fetchall()
    return [dict(r) for r in rows]


def apply_entity_rules(conn: sqlite3.Connection, cfg: Config, since: str | None = None) -> int:
    """Set entity_override (and flow override) on rows matching config.entity_rules."""
    if not cfg.entity_rules:
        return 0
    rules = [(re.compile(r.pattern, re.I), r.entity, r.flow_type) for r in cfg.entity_rules]
    sql = "SELECT id, description, merchant, entity_override FROM transactions"
    params: list[Any] = []
    if since:
        sql += " WHERE posted_at >= ?"
        params.append(since)
    n = 0
    for r in conn.execute(sql, params).fetchall():
        text = f"{r['merchant'] or ''} {r['description'] or ''}"
        for pat, entity, flow in rules:
            if pat.search(text):
                if r["entity_override"] != entity:
                    conn.execute("UPDATE transactions SET entity_override = ?, flow_type_override = COALESCE(?, flow_type_override),"
                                 " updated_at = ? WHERE id = ?", (entity, flow, now_iso(), r["id"]))
                    n += 1
                break
    return n


def pnl(conn: sqlite3.Connection, entity: str, months: int = 12) -> list[dict[str, Any]]:
    rows = conn.execute(f"""
        SELECT substr(posted_at,1,7) AS month,
               SUM(CASE WHEN flow IN ({_INC}) THEN amount ELSE 0 END) AS revenue,
               SUM(CASE WHEN flow IN ({_SP}) THEN amount ELSE 0 END) AS expenses,
               SUM(CASE WHEN flow = 'tax' THEN amount ELSE 0 END) AS taxes,
               SUM(CASE WHEN flow = 'transfer' THEN amount ELSE 0 END) AS transfers,
               COUNT(*) AS n
        FROM transactions_v WHERE entity = ? AND pending = 0
        GROUP BY month ORDER BY month DESC LIMIT ?""", (entity, months)).fetchall()
    out = []
    for r in rows:
        d = {k: (round(r[k], 2) if isinstance(r[k], float) else r[k]) for k in r.keys()}
        d["net"] = round(d["revenue"] + d["expenses"] + d["taxes"], 2)
        out.append(d)
    return list(reversed(out))


def summary(conn: sqlite3.Connection, months: int = 12) -> list[dict[str, Any]]:
    out = []
    for e in list_entities(conn):
        rows = pnl(conn, e["slug"], months)
        out.append({**e, "months": len(rows),
                    "revenue": round(sum(r["revenue"] for r in rows), 2),
                    "expenses": round(sum(r["expenses"] for r in rows), 2),
                    "net": round(sum(r["net"] for r in rows), 2)})
    return out


def review_queue(conn: sqlite3.Connection, months: int = 6, min_amount: float = 250) -> list[dict[str, Any]]:
    """Expenses on the personal entity that look like business spend, or large
    unexplained outflows, so they can be assigned to an entity."""
    rows = conn.execute(f"""
        SELECT id, posted_at, account_name, account_kind, amount, description, merchant, category, flow, entity
        FROM transactions_v
        WHERE entity = 'personal' AND pending = 0 AND flow IN ({_SP}, 'transfer', 'unknown')
          AND posted_at >= date('now', ?) AND amount <= -?
        ORDER BY amount""", (f"-{int(months)} months", min_amount)).fetchall()
    out = []
    for r in rows:
        text = f"{r['merchant'] or ''} {r['description'] or ''} {r['category'] or ''}"
        reason = None
        if BUSINESSY.search(text):
            reason = "business-looking merchant or category"
        elif r["flow"] == "unknown":
            reason = "unclassified"
        elif (-r["amount"] >= 5000 and r["flow"] == "transfer" and not INTERNAL.search(text)
              and r["account_kind"] in ("checking", "savings", "money_market", "cash_mgmt", "credit_card")
              and not conn.execute("SELECT 1 FROM transactions WHERE id = ? AND transfer_group IS NOT NULL",
                                   (r["id"],)).fetchone()):
            reason = "large unpaired transfer"
        if reason:
            d = dict(r)
            d["reason"] = reason
            out.append(d)
    return out
