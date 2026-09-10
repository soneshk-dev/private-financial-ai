"""Deterministic daily brief (no model involved). Sent to Telegram by the
brief timer and exposed as a tool for the chat loop."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from ..config import Config
from . import cashflow, health, overview, portfolio


def _m(v) -> str:
    v = float(v or 0)
    return f"-${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def daily_brief(conn: sqlite3.Connection, cfg: Config, today: date | None = None) -> str:
    today = today or date.today()
    yday = (today - timedelta(days=1)).isoformat()
    month = today.strftime("%Y-%m")
    lines = [f"*Daily brief · {today.isoformat()}*", ""]

    # Yesterday's spending
    rows = cashflow.search_transactions(conn, start=yday, end=yday, include_pending=True, limit=500)
    spend = [r for r in rows if r["flow"] in ("expense", "fee") and r["amount"] < 0]
    if spend:
        total = sum(r["amount"] for r in spend)
        lines.append(f"*Yesterday:* {len(spend)} purchases, {_m(-total)}")
        for r in sorted(spend, key=lambda r: r["amount"])[:5]:
            who = (r["merchant"] or r["description"] or "?")[:32]
            lines.append(f"• {_m(-r['amount'])} — {who} · {(r['category'] or '').split(' > ')[-1]}"
                         + (" (pending)" if r["pending"] else ""))
    else:
        lines.append("*Yesterday:* no purchases recorded")
    big = [r for r in rows if r["flow"] in ("income", "transfer", "loan_payment", "tax", "investment_buy", "investment_sell")
           and abs(r["amount"]) >= 5000]
    for r in big:
        lines.append(f"• {r['flow']}: {_m(r['amount'])} — {(r['merchant'] or r['description'] or '')[:32]}")
    lines.append("")

    # Month to date vs budget
    sp = cashflow.spending_by_category(conn, month)
    days_in = today.day
    lines.append(f"*Month to date:* {_m(sp['total'])} spent over {days_in} day{'s' if days_in != 1 else ''}")
    over = [b for b in cashflow.budget_status(conn, month) if b["status"] in ("over", "warning")]
    for b in sorted(over, key=lambda b: -(b["pct"] or 0))[:6]:
        lines.append(f"• {b['category']}: {_m(b['spent'])} of {_m(b['limit'])} ({int((b['pct'] or 0) * 100)}%)")
    lines.append("")

    # Net worth
    nw = overview.net_worth(conn, 30)
    delta = f" ({'+' if (nw['change'] or 0) >= 0 else ''}{_m(nw['change'])} 30d)" if nw.get("change") is not None else ""
    lines.append(f"*Net worth:* {_m(nw['net_worth'])}{delta} · assets {_m(nw['assets'])} · debt {_m(nw['liabilities'])}")
    aave = portfolio.aave_health(conn)
    if aave:
        lines.append(f"*Aave:* HF {aave['health_factor']} ({aave['status']}), BTC liq {_m(aave['liquidation_price_btc'] or 0)}")
    lines.append("")

    # Data issues
    h = health.status(conn)
    issues = [f"{c['connector']}: {(c['last_error'] or 'error')[:60]}" for c in h["connectors"] if c["status"] == "error"]
    issues += [f"{x['institution']}: {x['status']}" for x in h["connections"] if x["status"] not in ("active", "removed")]
    stale = [c["connector"] for c in h["connectors"] if c["status"] == "ok" and c["last_success_at"]
             and c["last_success_at"][:10] < (today - timedelta(days=3)).isoformat() and c["connector"] != "bitcoin"]
    if stale:
        issues.append("stale: " + ", ".join(stale))
    unknown = conn.execute("SELECT COUNT(*) FROM transactions_v WHERE flow = 'unknown' AND posted_at >= ?",
                           ((today - timedelta(days=30)).isoformat(),)).fetchone()[0]
    if unknown:
        issues.append(f"{unknown} unclassified inflow(s) in the last 30 days")
    lines.append("*Data:* " + ("; ".join(issues) if issues else "all connectors healthy"))
    return "\n".join(lines)
