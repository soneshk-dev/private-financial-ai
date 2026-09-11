"""Runway: how long liquid reserves last given the burn rate and the income that
is still coming (severance until a date, board fees, business draws)."""
from __future__ import annotations

import re
import sqlite3
from datetime import date
from typing import Any

from ..config import Config, KIND_CLASS
from ..ledger.classify import INCOME_FLOWS

_INC = ",".join(f"'{f}'" for f in INCOME_FLOWS)


def _month_add(d: date, n: int) -> date:
    y, m = d.year + (d.month - 1 + n) // 12, (d.month - 1 + n) % 12 + 1
    return date(y, m, 1)


def reserves(conn: sqlite3.Connection, cfg: Config) -> tuple[float, list[dict[str, Any]]]:
    classes = set(cfg.runway.reserve_classes) | set(cfg.runway.include_investment_classes)
    total, detail = 0.0, []
    for a in conn.execute("SELECT id, name, kind, entity FROM accounts WHERE is_active = 1 AND is_liability = 0"):
        if KIND_CLASS.get(a["kind"], "other") not in classes or a["entity"] != cfg.runway.entity:
            continue
        b = conn.execute("SELECT balance FROM balances_daily WHERE account_id = ? ORDER BY as_of DESC LIMIT 1", (a["id"],)).fetchone()
        v = float(b["balance"]) if b else 0.0
        if v == 0:
            p = conn.execute("SELECT SUM(value) FROM positions_latest WHERE account_id = ?", (a["id"],)).fetchone()[0]
            v = float(p or 0)
        total += v
        detail.append({"name": a["name"], "kind": a["kind"], "value": round(v, 2)})
    return round(total, 2), detail


def burn_rate(conn: sqlite3.Connection, cfg: Config, today: date) -> dict[str, Any]:
    start = _month_add(today.replace(day=1), -cfg.runway.burn_months).isoformat()
    end = today.replace(day=1).isoformat()   # full months only
    r = conn.execute("""
        SELECT COUNT(DISTINCT substr(posted_at,1,7)) AS months,
               SUM(CASE WHEN flow IN ('expense','fee','refund') THEN amount ELSE 0 END) AS spending,
               SUM(CASE WHEN flow = 'loan_payment' THEN amount ELSE 0 END) AS loans,
               SUM(CASE WHEN flow = 'tax' THEN amount ELSE 0 END) AS taxes
        FROM transactions_v WHERE entity = ? AND pending = 0 AND posted_at >= ? AND posted_at < ?""",
                     (cfg.runway.entity, start, end)).fetchone()
    months = max(int(r["months"] or 0), 1)
    spending = -float(r["spending"] or 0) / months
    loans = -float(r["loans"] or 0) / months
    taxes = -float(r["taxes"] or 0) / months
    return {"months_averaged": months, "spending": round(spending, 2), "loan_payments": round(loans, 2),
            "taxes": round(taxes, 2), "total": round(spending + loans + taxes, 2), "window": [start, end]}


def incomes(conn: sqlite3.Connection, cfg: Config, today: date) -> list[dict[str, Any]]:
    since = _month_add(today.replace(day=1), -3).isoformat()
    rows = conn.execute(f"SELECT posted_at, amount, description, merchant FROM transactions_v"
                        f" WHERE flow IN ({_INC}) AND pending = 0 AND posted_at >= ? AND entity = ?",
                        (since, cfg.runway.entity)).fetchall()
    out = []
    for inc in cfg.runway.incomes:
        pat = re.compile(inc.match, re.I)
        matched = [r for r in rows if pat.search(f"{r['merchant'] or ''} {r['description'] or ''}")]
        by_month: dict[str, float] = {}
        for r in matched:
            by_month[r["posted_at"][:7]] = by_month.get(r["posted_at"][:7], 0) + r["amount"]
        observed = round(sum(by_month.values()) / 3, 2)
        monthly = inc.monthly if inc.monthly is not None else observed
        out.append({"name": inc.name, "monthly": round(monthly, 2), "observed_monthly": observed,
                    "until": inc.until, "matches": len(matched)})
    return out


def project(conn: sqlite3.Connection, cfg: Config, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    reserve, reserve_detail = reserves(conn, cfg)
    burn = burn_rate(conn, cfg, today)
    incs = incomes(conn, cfg, today)
    series = []
    bal = reserve
    cliff = None
    start = today.replace(day=1)
    for i in range(cfg.runway.horizon_months + 1):
        m = _month_add(start, i)
        inc_total = sum(x["monthly"] for x in incs if not x["until"] or m.isoformat() <= x["until"][:10])
        if i > 0:
            bal += inc_total - burn["total"]
        series.append({"month": m.strftime("%Y-%m"), "reserve": round(bal, 2), "income": round(inc_total, 2),
                       "burn": burn["total"]})
        if cliff is None and bal < 0:
            cliff = m.strftime("%Y-%m")
    no_income_months = round(reserve / burn["total"], 1) if burn["total"] > 0 else None
    current_net = sum(x["monthly"] for x in incs if not x["until"] or start.isoformat() <= x["until"][:10]) - burn["total"]
    return {"as_of": today.isoformat(), "reserve": reserve, "reserve_detail": reserve_detail, "burn": burn,
            "incomes": incs, "net_monthly_now": round(current_net, 2), "months_no_income": no_income_months,
            "cliff_month": cliff, "reserve_at_horizon": series[-1]["reserve"], "series": series}
