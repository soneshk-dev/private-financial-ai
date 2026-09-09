"""Transactions: idempotent upserts keyed by provider id, pending→posted
replacement, removal, overrides, and transfer pairing."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import date, timedelta
from typing import Any

from ..db import now_iso
from .classify import apply_category_rules, infer_flow, normalize_category, Rule


def txn_id(source: str, source_txn_id: str) -> str:
    return "txn_" + hashlib.sha1(f"{source}:{source_txn_id}".encode()).hexdigest()[:20]


def upsert_transaction(conn: sqlite3.Connection, *, source: str, source_txn_id: str, account_id: str,
                       posted_at: str, amount: float, description: str | None = None,
                       merchant: str | None = None, category_raw: str | None = None,
                       category: str | None = None, currency: str = "USD", pending: bool = False,
                       authorized_at: str | None = None, entity: str | None = None,
                       account_kind: str | None = None, flow_type: str | None = None,
                       rules: list[Rule] | None = None, meta: dict[str, Any] | None = None,
                       replaces_source_txn_id: str | None = None) -> tuple[str, str]:
    """Insert or update. Returns (id, 'inserted'|'updated'|'replaced').

    ``replaces_source_txn_id`` handles pending→posted: the existing pending row
    is re-keyed to the posted id, keeping any user overrides, instead of a new
    row being added.
    """
    if account_kind is None or entity is None:
        row = conn.execute("SELECT kind, entity FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown account {account_id}")
        account_kind = account_kind or row["kind"]
        entity = entity or row["entity"]

    cat = category
    rule_flow = None
    if cat is None:
        rule_cat, rule_flow = apply_category_rules(conn, merchant, description)
        cat = rule_cat or normalize_category(category_raw, source if source in ("plaid", "fina") else None)
    flow = flow_type or rule_flow or infer_flow(cat, amount, account_kind, description, rules)

    new_id = txn_id(source, source_txn_id)
    ts = now_iso()
    status = "inserted"

    if replaces_source_txn_id and replaces_source_txn_id != source_txn_id:
        old_id = txn_id(source, replaces_source_txn_id)
        old = conn.execute("SELECT id FROM transactions WHERE id = ?", (old_id,)).fetchone()
        if old and not conn.execute("SELECT 1 FROM transactions WHERE id = ?", (new_id,)).fetchone():
            conn.execute("UPDATE transactions SET id = ?, source_txn_id = ?, updated_at = ? WHERE id = ?",
                         (new_id, source_txn_id, ts, old_id))
            status = "replaced"
        elif old:
            conn.execute("DELETE FROM transactions WHERE id = ?", (old_id,))

    existing = conn.execute("SELECT id FROM transactions WHERE id = ?", (new_id,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE transactions SET account_id=?, posted_at=?, authorized_at=?, amount=?, currency=?,"
            " description=?, merchant=?, category_raw=?, category=?, flow_type=?, entity=?, pending=?,"
            " meta=?, updated_at=? WHERE id=?",
            (account_id, posted_at, authorized_at, float(amount), currency, description, merchant,
             category_raw, cat, flow, entity, int(pending), json.dumps(meta or {}), ts, new_id))
        return new_id, ("replaced" if status == "replaced" else "updated")
    conn.execute(
        "INSERT INTO transactions (id, source, source_txn_id, account_id, posted_at, authorized_at, amount,"
        " currency, description, merchant, category_raw, category, flow_type, entity, pending, meta,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_id, source, source_txn_id, account_id, posted_at, authorized_at, float(amount), currency,
         description, merchant, category_raw, cat, flow, entity, int(pending), json.dumps(meta or {}), ts, ts))
    return new_id, "inserted"


def remove_transaction(conn: sqlite3.Connection, source: str, source_txn_id: str) -> bool:
    cur = conn.execute("DELETE FROM transactions WHERE id = ?", (txn_id(source, source_txn_id),))
    return cur.rowcount > 0


def set_override(conn: sqlite3.Connection, tid: str, *, flow_type: str | None = None,
                 category: str | None = None) -> None:
    conn.execute("UPDATE transactions SET flow_type_override = COALESCE(?, flow_type_override),"
                 " category_override = COALESCE(?, category_override), updated_at = ? WHERE id = ?",
                 (flow_type, category, now_iso(), tid))


def reclassify_all(conn: sqlite3.Connection, rules: list[Rule] | None = None) -> int:
    """Recompute flow_type for every row (overrides untouched)."""
    rows = conn.execute("SELECT t.id, t.category, t.amount, a.kind, t.description FROM transactions t"
                        " JOIN accounts a ON a.id = t.account_id").fetchall()
    n = 0
    for r in rows:
        flow = infer_flow(r["category"], r["amount"], r["kind"], r["description"], rules)
        conn.execute("UPDATE transactions SET flow_type = ? WHERE id = ? AND flow_type != ?", (flow, r["id"], flow))
        n += 1
    return n


def pair_transfers(conn: sqlite3.Connection, window_days: int = 3, since: str | None = None) -> int:
    """Group opposite-signed equal-amount transactions across two accounts.

    Only rows already classed as ``transfer`` (or ``loan_payment`` into an own
    liability account) are candidates, so a coincidental matching purchase and
    refund are never paired. Returns the number of pairs created.
    """
    sql = ("SELECT id, account_id, posted_at, amount, flow_type, flow_type_override FROM transactions"
           " WHERE transfer_group IS NULL AND COALESCE(flow_type_override, flow_type) IN ('transfer','loan_payment')")
    params: list[Any] = []
    if since:
        sql += " AND posted_at >= ?"
        params.append(since)
    rows = [dict(r) for r in conn.execute(sql + " ORDER BY posted_at", params)]
    by_amount: dict[float, list[dict]] = {}
    for r in rows:
        by_amount.setdefault(round(abs(r["amount"]), 2), []).append(r)
    pairs = 0
    used: set[str] = set()
    for amt, group in by_amount.items():
        if amt == 0 or len(group) < 2:
            continue
        for a in group:
            if a["id"] in used:
                continue
            ad = date.fromisoformat(a["posted_at"][:10])
            best = None
            for b in group:
                if b["id"] in used or b["id"] == a["id"] or b["account_id"] == a["account_id"]:
                    continue
                if (a["amount"] > 0) == (b["amount"] > 0):
                    continue
                bd = date.fromisoformat(b["posted_at"][:10])
                if abs((ad - bd).days) <= window_days:
                    if best is None or abs((ad - bd).days) < best[0]:
                        best = (abs((ad - bd).days), b)
            if best:
                gid = "xfer_" + uuid.uuid4().hex[:12]
                conn.execute("UPDATE transactions SET transfer_group = ? WHERE id IN (?, ?)",
                             (gid, a["id"], best[1]["id"]))
                used.add(a["id"])
                used.add(best[1]["id"])
                pairs += 1
    return pairs


def month_bounds(month: str) -> tuple[str, str]:
    y, m = int(month[:4]), int(month[5:7])
    start = date(y, m, 1)
    end = date(y + (m // 12), (m % 12) + 1, 1) - timedelta(days=1)
    return start.isoformat(), end.isoformat()
