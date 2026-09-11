"""Threshold alerts evaluated after every sync; each fires once per day."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import Any

from ..config import Config
from ..db import now_iso
from . import cashflow, health, portfolio, runway


def evaluate(conn: sqlite3.Connection, cfg: Config, today: date | None = None) -> list[dict[str, str]]:
    today = today or date.today()
    a = cfg.alerts
    out: list[dict[str, str]] = []
    hf = portfolio.aave_health(conn)
    if hf and hf["health_factor"] < a.aave_hf_below:
        out.append({"key": "aave_hf", "text": f"⚠ Aave health factor {hf['health_factor']} is below {a.aave_hf_below}"
                                             f" (BTC liquidation ${hf['liquidation_price_btc']:,.0f})"})
    if a.budget_over:
        for b in cashflow.budget_status(conn, today.strftime("%Y-%m")):
            if b["status"] == "over":
                out.append({"key": f"budget_{b['category']}", "text": f"Budget over: {b['category']} ${b['spent']:,.0f} of ${b['limit']:,.0f}"})
    if a.large_transaction:
        yday = (today - timedelta(days=1)).isoformat()
        for t in cashflow.search_transactions(conn, start=yday, end=today.isoformat(), limit=500):
            if t["flow"] in ("expense", "fee") and -t["amount"] >= a.large_transaction:
                out.append({"key": f"large_{t['id']}", "text": f"Large charge: ${-t['amount']:,.0f} at {(t['merchant'] or t['description'] or '?')[:40]} ({t['account_name']})"})
    if a.connector_errors:
        h = health.status(conn)
        for c in h["connectors"]:
            if c["status"] == "error":
                out.append({"key": f"connector_{c['connector']}", "text": f"Connector {c['connector']} failed: {(c['last_error'] or '')[:80]}"})
        for x in h["connections"]:
            if x["status"] == "login_required":
                out.append({"key": f"login_{x['id']}", "text": f"{x['institution']} needs re-login"})
    if a.unknown_inflows:
        n = conn.execute("SELECT COUNT(*) FROM transactions_v WHERE flow = 'unknown' AND posted_at >= ?",
                         ((today - timedelta(days=7)).isoformat(),)).fetchone()[0]
        if n:
            out.append({"key": "unknown_inflows", "text": f"{n} unclassified inflow(s) this week"})
    if a.runway_months_below and cfg.runway.incomes is not None:
        try:
            r = runway.project(conn, cfg, today)
            if r["months_no_income"] is not None and r["months_no_income"] < a.runway_months_below:
                out.append({"key": "runway", "text": f"Runway without income is {r['months_no_income']} months"})
            if r["cliff_month"]:
                out.append({"key": f"cliff_{r['cliff_month']}", "text": f"Projected reserves go negative in {r['cliff_month']}"})
        except Exception:  # noqa: BLE001
            pass
    return out


def send_new(conn: sqlite3.Connection, cfg: Config, alerts: list[dict[str, str]], today: date | None = None) -> dict[str, Any]:
    from ..notify import telegram
    today = today or date.today()
    fresh = []
    for al in alerts:
        key = f"{al['key']}:{today.isoformat()}"
        if conn.execute("SELECT 1 FROM alerts_sent WHERE key = ?", (key,)).fetchone():
            continue
        fresh.append((key, al))
    if not fresh:
        return {"sent": 0, "pending": 0}
    text = "*homeai alerts*\n" + "\n".join(f"• {al['text']}" for _, al in fresh)
    res = telegram.send(cfg, text) if telegram.configured(cfg) else {"ok": False, "error": "telegram not configured"}
    if res.get("ok"):
        conn.execute("BEGIN")
        for key, al in fresh:
            conn.execute("INSERT OR REPLACE INTO alerts_sent (key, sent_at, payload) VALUES (?,?,?)", (key, now_iso(), json.dumps(al)))
        conn.execute("COMMIT")
    return {"sent": len(fresh) if res.get("ok") else 0, "pending": len(fresh), "result": res}
