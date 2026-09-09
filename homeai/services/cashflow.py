"""Cash flow, spending and budgets, all read through ``transactions_v`` (overrides applied)."""
from __future__ import annotations

import sqlite3
from typing import Any

from ..ledger.classify import INCOME_FLOWS, SPENDING_FLOWS
from ..ledger.transactions import month_bounds

_INCOME = ",".join(f"'{f}'" for f in INCOME_FLOWS)
_SPEND = ",".join(f"'{f}'" for f in SPENDING_FLOWS)


def monthly_cashflow(conn: sqlite3.Connection, months: int = 12, entity: str | None = None) -> list[dict[str, Any]]:
    where = "pending = 0"
    params: list[Any] = []
    if entity:
        where += " AND entity = ?"
        params.append(entity)
    rows = conn.execute(f"""
        SELECT substr(posted_at, 1, 7) AS month,
               SUM(CASE WHEN flow IN ({_INCOME}) THEN amount ELSE 0 END)                 AS income,
               SUM(CASE WHEN flow IN ({_SPEND}) THEN amount ELSE 0 END)                  AS spending,
               SUM(CASE WHEN flow = 'tax' THEN amount ELSE 0 END)                        AS taxes,
               SUM(CASE WHEN flow = 'loan_payment' THEN amount ELSE 0 END)               AS loan_payments,
               SUM(CASE WHEN flow IN ('investment_buy','investment_sell') THEN amount ELSE 0 END) AS investing,
               SUM(CASE WHEN flow = 'transfer' THEN amount ELSE 0 END)                   AS transfers,
               SUM(CASE WHEN flow = 'unknown' THEN amount ELSE 0 END)                    AS unknown,
               COUNT(*) AS n
        FROM transactions_v WHERE {where}
        GROUP BY month ORDER BY month DESC LIMIT ?""", (*params, months)).fetchall()
    out = []
    for r in rows:
        d = {k: (round(r[k], 2) if isinstance(r[k], float) else r[k]) for k in r.keys()}
        d["net"] = round(d["income"] + d["spending"] + d["taxes"] + d["loan_payments"] + d["investing"] + d["unknown"], 2)
        out.append(d)
    return list(reversed(out))


def spending_by_category(conn: sqlite3.Connection, month: str, entity: str | None = None) -> dict[str, Any]:
    start, end = month_bounds(month)
    where = f"pending = 0 AND flow IN ({_SPEND}) AND posted_at BETWEEN ? AND ?"
    params: list[Any] = [start, end]
    if entity:
        where += " AND entity = ?"
        params.append(entity)
    l1 = conn.execute(f"SELECT category_l1 AS category, ROUND(-SUM(amount),2) AS spent, COUNT(*) AS n"
                      f" FROM transactions_v WHERE {where} GROUP BY category_l1 ORDER BY spent DESC", params).fetchall()
    full = conn.execute(f"SELECT category, ROUND(-SUM(amount),2) AS spent, COUNT(*) AS n"
                        f" FROM transactions_v WHERE {where} GROUP BY category ORDER BY spent DESC", params).fetchall()
    merchants = conn.execute(f"SELECT COALESCE(merchant, description) AS merchant, ROUND(-SUM(amount),2) AS spent,"
                             f" COUNT(*) AS n FROM transactions_v WHERE {where} GROUP BY 1 ORDER BY spent DESC LIMIT 25",
                             params).fetchall()
    total = round(sum(r["spent"] for r in l1), 2)
    return {"month": month, "total": total, "by_level1": [dict(r) for r in l1], "by_category": [dict(r) for r in full],
            "top_merchants": [dict(r) for r in merchants]}


def search_transactions(conn: sqlite3.Connection, *, start: str | None = None, end: str | None = None,
                        account_id: str | None = None, flow: str | None = None, category: str | None = None,
                        q: str | None = None, entity: str | None = None, include_pending: bool = True,
                        limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    clauses, params = [], []
    if start:
        clauses.append("posted_at >= ?"); params.append(start)
    if end:
        clauses.append("posted_at <= ?"); params.append(end)
    if account_id:
        clauses.append("account_id = ?"); params.append(account_id)
    if flow:
        clauses.append("flow = ?"); params.append(flow)
    if category:
        clauses.append("(category = ? OR category_l1 = ?)"); params.extend([category, category])
    if entity:
        clauses.append("entity = ?"); params.append(entity)
    if q:
        clauses.append("(description LIKE ? OR merchant LIKE ?)"); params.extend([f"%{q}%", f"%{q}%"])
    if not include_pending:
        clauses.append("pending = 0")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(f"SELECT * FROM transactions_v{where} ORDER BY posted_at DESC, id LIMIT ? OFFSET ?",
                        (*params, min(int(limit), 2000), int(offset))).fetchall()
    return [dict(r) for r in rows]


def budget_status(conn: sqlite3.Connection, month: str) -> list[dict[str, Any]]:
    start, end = month_bounds(month)
    spent = {r["category_l1"]: -r["s"] for r in conn.execute(
        f"SELECT category_l1, SUM(amount) AS s FROM transactions_v WHERE pending = 0 AND flow IN ({_SPEND})"
        " AND posted_at BETWEEN ? AND ? GROUP BY category_l1", (start, end))}
    out = []
    for b in conn.execute("SELECT * FROM budgets WHERE is_active = 1 AND effective_from <= ?"
                          " AND (effective_until IS NULL OR effective_until >= ?) ORDER BY category_l1", (end, start)):
        s = round(spent.get(b["category_l1"], 0.0), 2)
        pct = round(s / b["monthly_limit"], 3) if b["monthly_limit"] else None
        out.append({"category": b["category_l1"], "limit": b["monthly_limit"], "spent": s, "pct": pct,
                    "status": "over" if pct and pct >= 1 else ("warning" if pct and pct >= b["alert_threshold"] else "ok")})
    return out


def flow_breakdown(conn: sqlite3.Connection, start: str, end: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT flow, ROUND(SUM(amount),2) AS total, COUNT(*) AS n FROM transactions_v"
                        " WHERE pending = 0 AND posted_at BETWEEN ? AND ? GROUP BY flow ORDER BY total", (start, end))
    return [dict(r) for r in rows]
