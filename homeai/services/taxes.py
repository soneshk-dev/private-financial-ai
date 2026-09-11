"""Transition-year tax estimate. Transparent arithmetic over what the ledger can
see, with the inputs it cannot see (withholding, gross wages, capital gains)
supplied by config. An estimate for planning, not a return."""
from __future__ import annotations

import re
import sqlite3
from datetime import date
from typing import Any

from ..config import Config
from ..ledger.classify import INCOME_FLOWS

_INC = ",".join(f"'{f}'" for f in INCOME_FLOWS)


def federal_tax(taxable: float, brackets: list[list[float]]) -> tuple[float, float, list[dict[str, float]]]:
    """Return (tax, marginal_rate, per-bracket detail)."""
    tax, lower, marginal, detail = 0.0, 0.0, brackets[0][1], []
    for upper, rate in brackets:
        if taxable <= lower:
            break
        span = min(taxable, upper) - lower
        tax += span * rate
        marginal = rate
        detail.append({"upper": upper, "rate": rate, "amount": round(span, 2), "tax": round(span * rate, 2)})
        lower = upper
    return round(tax, 2), marginal, detail


def _sum(conn, flows: str, patterns: list[str], year: int, entity: str | None = None, negate=False) -> float:
    rows = conn.execute(f"SELECT amount, description, merchant, entity FROM transactions_v"
                        f" WHERE flow IN ({flows}) AND pending = 0 AND posted_at BETWEEN ? AND ?",
                        (f"{year}-01-01", f"{year}-12-31")).fetchall()
    pats = [re.compile(p, re.I) for p in patterns]
    total = 0.0
    for r in rows:
        if entity and r["entity"] != entity:
            continue
        text = f"{r['merchant'] or ''} {r['description'] or ''}"
        if not pats or any(p.search(text) for p in pats):
            total += -r["amount"] if negate else r["amount"]
    return round(total, 2)


def estimate(conn: sqlite3.Connection, cfg: Config, today: date | None = None) -> dict[str, Any]:
    t = cfg.tax
    today = today or date.today()
    y = t.year
    wages_net = _sum(conn, "'income'", t.wage_patterns, y, entity="personal")
    wages = t.gross_wages_ytd if t.gross_wages_ytd is not None else wages_net
    other_income = _sum(conn, "'income'", [], y, entity="personal") - wages_net
    invest_income = _sum(conn, "'dividend','interest'", [], y)
    business = {}
    for e in conn.execute("SELECT slug FROM entities WHERE kind = 'business' AND is_active = 1"):
        rev = _sum(conn, _INC, [], y, entity=e["slug"])
        exp = _sum(conn, "'expense','fee','refund'", [], y, entity=e["slug"])
        business[e["slug"]] = {"revenue": rev, "expenses": exp, "net": round(rev + exp, 2)}
    business_net = round(sum(b["net"] for b in business.values()), 2)
    additional = dict(t.additional_income)
    agi = wages + other_income + invest_income + business_net + sum(additional.values())
    taxable = max(agi - t.standard_deduction, 0)
    fed, marginal, detail = federal_tax(taxable, t.brackets)
    niit = round(max(min(invest_income + additional.get("capital_gains", 0), max(agi - t.niit_threshold, 0)), 0) * 0.038, 2)
    state = round(max(agi, 0) * t.state_rate, 2)
    total = round(fed + niit + state, 2)

    fed_paid = _sum(conn, "'tax'", t.federal_payment_patterns, y, negate=True) + t.withholding_federal_ytd
    state_paid = _sum(conn, "'tax'", t.state_payment_patterns, y, negate=True) + t.withholding_state_ytd
    remaining_fed = round(fed + niit - fed_paid, 2)
    remaining_state = round(state - state_paid, 2)

    safe_harbor = None
    if t.prior_year_total_tax:
        mult = 1.10 if (t.prior_year_agi or 0) > 150000 else 1.0
        required = round(t.prior_year_total_tax * mult, 2)
        safe_harbor = {"required_payments": required, "multiplier": mult, "paid": round(fed_paid, 2),
                       "shortfall": round(max(required - fed_paid, 0), 2), "met": fed_paid >= required}

    # remaining estimated-tax due dates for the year
    dates = [d for d in (date(y, 4, 15), date(y, 6, 15), date(y, 9, 15), date(y + 1, 1, 15)) if d >= today]
    schedule = []
    if dates and remaining_fed > 0:
        per = round(remaining_fed / len(dates), 2)
        schedule = [{"due": d.isoformat(), "federal": per, "state": round(max(remaining_state, 0) / len(dates), 2)} for d in dates]

    # Roth-conversion headroom: room left in the current bracket
    current_upper = next((b[0] for b in t.brackets if taxable < b[0]), None)
    headroom = round(current_upper - taxable, 2) if current_upper and current_upper < 1e17 else None

    return {
        "year": y, "as_of": today.isoformat(), "filing_status": t.filing_status,
        "income": {"wages": wages, "wages_source": "gross (config)" if t.gross_wages_ytd is not None else "net deposits (gross unknown)",
                   "other_personal_income": other_income, "investment_income": invest_income,
                   "business": business, "business_net": business_net, "additional": additional, "agi": round(agi, 2)},
        "deductions": {"standard": t.standard_deduction}, "taxable_income": round(taxable, 2),
        "federal": {"tax": fed, "niit": niit, "marginal_rate": marginal, "brackets": detail,
                    "paid": round(fed_paid, 2), "remaining": remaining_fed},
        "state": {"rate": t.state_rate, "tax": state, "paid": round(state_paid, 2), "remaining": remaining_state},
        "total_tax": total, "effective_rate": round(total / agi, 3) if agi > 0 else None,
        "safe_harbor": safe_harbor, "schedule": schedule, "roth_headroom_in_bracket": headroom,
        "caveats": ["Wages are measured from net deposits unless gross_wages_ytd is set; withholding must be supplied.",
                    "Capital gains, K-1s and other items come from tax.additional_income.",
                    "Brackets and deduction are config values; verify against IRS figures for the year."],
    }
