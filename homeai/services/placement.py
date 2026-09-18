"""Where should a position live? Ranks accounts for a proposed trade by the tax cost of the
round trip, what the account can trade, and the cash on hand there. Frames consequences;
it does not recommend instruments."""
from __future__ import annotations

import sqlite3
from typing import Any

from ..config import Config
from .allocation import allocation, classify_position
from .taxes import estimate


def rates(conn: sqlite3.Connection, cfg: Config) -> dict[str, Any]:
    est = estimate(conn, cfg)
    taxable = est["taxable_income"]
    fed = est["federal"]["marginal_rate"]
    ltcg = next((r for ub, r in cfg.tax.ltcg_brackets if taxable < ub), cfg.tax.ltcg_brackets[-1][1])
    niit = 0.038 if est["income"]["agi"] > cfg.tax.niit_threshold else 0.0
    state = cfg.tax.state_rate
    return {"federal_marginal": fed, "ltcg": ltcg, "niit": niit, "state": state,
            "short_term_total": round(fed + niit + state, 4), "long_term_total": round(ltcg + niit + state, 4),
            "basis": f"{cfg.tax.year} estimate from the ledger: taxable income ${taxable:,.0f}"
                     + ("" if cfg.tax.gross_wages_ytd is not None else " (wages from net deposits; set gross wages for accuracy)")}


def _cash_by_account(alloc: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for h in alloc["holdings"]:
        if h["classes"].get("cash", 0) >= 0.99:
            out[h["account_id"]] = out.get(h["account_id"], 0.0) + h["value"]
    return out


def place(conn: sqlite3.Connection, cfg: Config, *, symbol: str | None = None, amount: float = 0,
          holding_months: int = 12, expected_return_pct: float = 10.0, alloc: dict[str, Any] | None = None) -> dict[str, Any]:
    alloc = alloc or allocation(conn, cfg)
    r = rates(conn, cfg)
    cash = _cash_by_account(alloc)
    gain = amount * expected_return_pct / 100
    short = holding_months < 12
    options = []
    for a in alloc["accounts"]:
        if a["role"] not in ("core", "thesis") or a["tradability"] not in ("open", "menu"):
            continue
        held_here = any(h["account_id"] == a["id"] and symbol and (h["symbol"] or "").upper() == symbol.upper()
                        for h in alloc["holdings"])
        if a["tradability"] == "menu" and not held_here:
            continue                      # a plan menu can only hold what it offers
        tt = a["tax_treatment"]
        if tt == "taxable":
            rate = r["short_term_total"] if short else r["long_term_total"]
            note = (f"gain taxed as {'short-term (ordinary)' if short else 'long-term'} at about {rate:.0%};"
                    " losses are harvestable; wash-sale rule applies across all your accounts")
        elif tt in ("tax_free", "tax_free_medical", "tax_free_education"):
            rate, note = 0.0, "no tax on the trade or on qualified withdrawals; losses cannot be deducted; space is scarce"
        elif tt == "tax_deferred":
            rate, note = 0.0, "no tax on the trade; the whole balance is ordinary income when withdrawn; losses cannot be deducted"
        else:
            rate, note = 0.0, tt.replace("_", " ")
        tax = max(gain, 0) * rate
        avail = cash.get(a["id"], 0.0)
        options.append({"account_id": a["id"], "account": a["name"], "tax_treatment": tt, "tradability": a["tradability"],
                        "restrictions": a["restrictions"], "tax_rate_on_gain": round(rate, 4),
                        "tax_on_expected_gain": round(tax, 0), "after_tax_gain": round(gain - tax, 0),
                        "cash_available": round(avail, 0), "funded_from_cash": avail >= amount > 0,
                        "already_holds": held_here, "note": note})
    # lowest tax first; among equals prefer an account that can fund it from cash; short horizons avoid scarce tax-free space
    def key(o):
        scarce = 1 if (o["tax_treatment"].startswith("tax_free") and short) else 0
        return (o["tax_on_expected_gain"], 0 if o["funded_from_cash"] else 1, scarce, -o["cash_available"])
    options.sort(key=key)
    return {"symbol": symbol, "amount": amount, "holding_months": holding_months, "expected_return_pct": expected_return_pct,
            "expected_gain": round(gain, 0), "rates": r, "options": options,
            "rules": ["Holding under 12 months: a taxable account pays ordinary rates, so tax-advantaged accounts come first.",
                      "Tax-free space (Roth, HSA) is scarce: best used for the highest expected long-run growth, not short trades.",
                      "A 401k brokerage window cannot short, use margin or trade options; bearish views need long instruments."]}


def analyze_expression(conn: sqlite3.Connection, cfg: Config, *, symbols: list[str], amount: float,
                       holding_months: int = 12, expected_return_pct: float = 10.0, thesis_slug: str | None = None,
                       fetch: bool = True) -> dict[str, Any]:
    """For each candidate instrument: price and recent return, look-through class, what you already hold,
    where it would live, and what it does to the thesis budget and policy drift."""
    from .market import latest_price, price_history
    from .theses import budget_status
    alloc = allocation(conn, cfg)
    settings = alloc["settings"]
    out = []
    per = amount / max(len(symbols), 1)
    for sym in [s.upper().strip() for s in symbols if s.strip()]:
        if fetch and len(price_history(conn, sym, 5)) < 5:
            try:
                from ..connectors.market import MarketConnector
                conn.execute("BEGIN"); MarketConnector(cfg).fetch_symbol(conn, sym); conn.execute("COMMIT")
            except Exception:  # noqa: BLE001
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
        hist = price_history(conn, sym, 130)
        px = latest_price(conn, sym)
        def ret(n):
            return round((hist[-1]["value"] / hist[-n - 1]["value"] - 1) * 100, 1) if len(hist) > n else None
        weights, how = classify_position(sym, None, "etf", settings.get("exposures") or {})
        held = [{"account": h["account_name"], "value": h["value"], "tax_treatment": h["tax_treatment"]}
                for h in alloc["holdings"] if (h["symbol"] or "").upper() == sym]
        cls = max(weights, key=weights.get)
        row = next((r for r in alloc["by_class"] if r["class"] == cls), None)
        after_pct = None
        if row and row["pct"] is not None and alloc["investable"]:
            after_pct = round((row["value"] + per * weights[cls]) / alloc["investable"] * 100, 1)   # funded from cash inside the sleeve
        out.append({"symbol": sym, "price": px, "return_1m_pct": ret(21), "return_3m_pct": ret(63),
                    "class": cls, "class_source": how, "class_now_pct": row["pct"] if row else None,
                    "class_after_pct": after_pct, "class_policy_pct": row["policy_pct"] if row else None,
                    "already_held": held, "already_held_value": round(sum(h["value"] for h in held), 0),
                    "never_sell": sym in (settings.get("never_sell") or []),
                    "placement": place(conn, cfg, symbol=sym, amount=per, holding_months=holding_months,
                                       expected_return_pct=expected_return_pct, alloc=alloc)["options"][:3]})
    b = budget_status(conn, cfg, alloc)
    return {"amount": amount, "per_symbol": round(per, 0), "holding_months": holding_months,
            "expected_return_pct": expected_return_pct, "candidates": out, "rates": rates(conn, cfg),
            "thesis_budget": {**b, "after_this": round(b["remaining"] - amount, 0), "fits": amount <= b["remaining"]},
            "note": "Frames consequences only: sizing, tax, placement and overlap. The choice of instrument and the view are yours."}
