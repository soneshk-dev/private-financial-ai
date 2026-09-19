"""Goal and retirement projections. A small seeded Monte Carlo (lognormal monthly returns) in plain
Python: no cloud, no heavy dependencies, the same answer every run. Assumptions are editable in the
app (settings key ``plan``); the defaults here are placeholders, not forecasts."""
from __future__ import annotations

import json
import math
import random
import sqlite3
from datetime import date
from typing import Any

from ..config import Config
from ..db import now_iso
from . import goals as goals_svc

KEY = "plan"
# nominal expected return %, volatility % per look-through class
DEFAULT_CLASS_ASSUMPTIONS = {
    "us_equity": [7.0, 16.0], "intl_equity": [6.5, 17.0], "em_equity": [7.5, 22.0], "bonds": [4.5, 6.0],
    "gold": [4.0, 15.0], "btc": [12.0, 60.0], "eth": [12.0, 75.0], "other_crypto": [10.0, 80.0],
    "cash": [4.0, 0.5], "other": [4.0, 10.0]}
# when a goal has no linked holdings: by years left -> [return %, vol %] (a glide path toward safety)
DEFAULT_GLIDE = [[2, 3.8, 2.0], [5, 5.0, 7.0], [10, 6.0, 11.0], [99, 7.0, 15.0]]
DEFAULTS: dict[str, Any] = {
    "paths": 1000, "correlation": 0.3, "inflation_pct": 2.5, "confidence_pct": 80,
    "class_assumptions": DEFAULT_CLASS_ASSUMPTIONS, "glide": DEFAULT_GLIDE,
    "goals": {},            # slug -> {monthly_contribution, target_amount, target_date, return_pct, vol_pct, debt_rate_pct, monthly_payment}
    "retirement": {"current_age": None, "retire_age": 60, "end_age": 95, "annual_spend": None, "annual_contribution": 0,
                   "other_income": 0, "other_income_age": 67, "include_classes": ["retirement", "investments", "crypto"],
                   "crypto_haircut_pct": 50},
}


def get_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (KEY,)).fetchone()
    out = json.loads(json.dumps(DEFAULTS))
    if row:
        saved = json.loads(row["value"]) or {}
        for k, v in saved.items():
            if k == "retirement":
                out["retirement"].update(v or {})
            else:
                out[k] = v
    return out


def save_settings(conn: sqlite3.Connection, patch: dict[str, Any]) -> dict[str, Any]:
    cur = get_settings(conn)
    for k, v in patch.items():
        if k not in DEFAULTS:
            raise ValueError(f"unknown plan setting {k}")
        if k == "retirement":
            bad = [x for x in v if x not in DEFAULTS["retirement"]]
            if bad:
                raise ValueError(f"unknown retirement settings: {', '.join(bad)}")
            cur["retirement"].update(v)
        elif k == "goals":
            for slug, g in (v or {}).items():
                merged = {**cur["goals"].get(slug, {}), **(g or {})}
                cur["goals"][slug] = {a: b for a, b in merged.items() if b not in (None, "")}
        elif k == "paths":
            cur[k] = max(200, min(5000, int(v)))
        elif k in ("correlation",):
            cur[k] = max(0.0, min(1.0, float(v)))
        elif k in ("inflation_pct", "confidence_pct"):
            cur[k] = float(v)
        else:
            cur[k] = v
    r = cur["retirement"]
    if r.get("current_age") is not None and r.get("retire_age") is not None and not (0 < r["current_age"] < r["end_age"]):
        raise ValueError("ages must satisfy 0 < current_age < end_age")
    conn.execute("BEGIN")
    conn.execute("INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
                 " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                 (KEY, json.dumps(cur), now_iso()))
    conn.commit()
    return cur


# --- the engine ------------------------------------------------------------------
def simulate(start: float, monthly: float, months: int, return_pct: float, vol_pct: float, *, paths: int = 1000,
             seed: int = 7, target: float | None = None, schedule: list[float] | None = None) -> dict[str, Any]:
    """Monthly lognormal paths. ``schedule`` overrides ``monthly`` with a per-month cash flow (negative = withdrawal);
    a path that hits zero stays at zero. Returns yearly percentiles, the end distribution and P(end >= target)."""
    months = max(int(months), 0)
    mu, sigma = return_pct / 100, vol_pct / 100
    m_sigma = sigma / math.sqrt(12)
    m_mu = math.log(1 + mu) / 12 - 0.5 * m_sigma ** 2
    rng = random.Random(seed)
    marks = sorted({m for m in range(12, months + 1, 12)} | {months}) if months else [0]
    snaps: dict[int, list[float]] = {m: [] for m in marks}
    depleted = 0
    for _ in range(paths):
        v = start
        dead = False
        for m in range(1, months + 1):
            v = v * math.exp(m_mu + m_sigma * rng.gauss(0, 1)) + (schedule[m - 1] if schedule else monthly)
            if v <= 0:
                v, dead = 0.0, True
            if m in snaps:
                snaps[m].append(v)
        depleted += dead
        if not months:
            snaps[0].append(v)
    def q(xs: list[float], p: float) -> float:
        xs = sorted(xs)
        return xs[min(int(p * (len(xs) - 1) + 0.5), len(xs) - 1)]
    series = [{"month": m, "p10": round(q(v, .10)), "p50": round(q(v, .50)), "p90": round(q(v, .90))} for m, v in snaps.items()]
    end = snaps[marks[-1]]
    return {"series": [{"month": 0, "p10": round(start), "p50": round(start), "p90": round(start)}] + series if months else series,
            "end": {"p10": round(q(end, .10)), "p50": round(q(end, .50)), "p90": round(q(end, .90))},
            "probability": round(sum(1 for x in end if x >= target) / len(end), 3) if target is not None else None,
            "depleted_probability": round(depleted / paths, 3)}


def required_monthly(start: float, months: int, return_pct: float, vol_pct: float, target: float, confidence: float,
                     hi: float | None = None) -> float | None:
    """Smallest monthly saving that reaches ``target`` with the given confidence."""
    if months <= 0:
        return None
    if simulate(start, 0, months, return_pct, vol_pct, paths=300, target=target)["probability"] >= confidence:
        return 0.0
    lo, hi = 0.0, hi or max(target / months * 1.5, 100.0)
    for _ in range(14):
        mid = (lo + hi) / 2
        if simulate(start, mid, months, return_pct, vol_pct, paths=300, target=target)["probability"] >= confidence:
            hi = mid
        else:
            lo = mid
    return round(hi, -1)


def mix_assumption(weights: dict[str, float], ca: dict[str, list[float]], rho: float) -> tuple[float, float]:
    tot = sum(weights.values()) or 1
    w = {k: v / tot for k, v in weights.items() if v > 0}
    ret = sum(wt * ca.get(k, ca["other"])[0] for k, wt in w.items())
    ks = list(w)
    var = sum((w[k] * ca.get(k, ca["other"])[1]) ** 2 for k in ks)
    var += 2 * rho * sum(w[a] * w[b] * ca.get(a, ca["other"])[1] * ca.get(b, ca["other"])[1]
                         for i, a in enumerate(ks) for b in ks[i + 1:])
    return round(ret, 2), round(math.sqrt(var), 2)


def _glide(years: float, glide: list[list[float]]) -> tuple[float, float]:
    for ub, r, v in glide:
        if years <= ub:
            return r, v
    return glide[-1][1], glide[-1][2]


def goal_projections(conn: sqlite3.Connection, cfg: Config, today: date | None = None) -> list[dict[str, Any]]:
    from .allocation import allocation
    today = today or date.today()
    s = get_settings(conn)
    holdings = allocation(conn, cfg)["holdings"]
    out = []
    for g in goals_svc.progress(conn, today):
        ov = s["goals"].get(g["slug"], {})
        target = ov.get("target_amount", g["target_amount"])
        tdate = ov.get("target_date", g["target_date"])
        monthly = float(ov.get("monthly_contribution", g["monthly_contribution"] or 0) or 0)
        months = None
        if tdate:
            td = date.fromisoformat(str(tdate)[:10])
            months = max((td.year - today.year) * 12 + td.month - today.month, 0)
        row: dict[str, Any] = {**g, "target_amount": target, "target_date": tdate, "months_left": months,
                               "monthly_contribution": monthly, "overrides": ov}
        if g["kind"] == "debt":
            rate = float(ov.get("debt_rate_pct", 8.0)) / 100 / 12
            pay = float(ov.get("monthly_payment", monthly) or 0)
            bal, n, path = g["current"], 0, [{"month": 0, "p50": round(g["current"])}]
            while bal > 0 and pay > bal * rate and n < 600:
                bal = bal * (1 + rate) - pay; n += 1
                if n % 12 == 0 or bal <= 0:
                    path.append({"month": n, "p50": round(max(bal, 0))})
            row["projection"] = {"kind": "debt", "rate_pct": ov.get("debt_rate_pct", 8.0), "monthly_payment": pay,
                                 "payoff_months": n if bal <= 0 else None, "series": path,
                                 "interest_per_month_now": round(g["current"] * rate)}
        elif g["kind"] in ("save", "purchase", "retirement") and target and months:
            mix: dict[str, float] = {}
            for h in holdings:
                if h["account_id"] in (g.get("linked_accounts") or []):
                    for c, w in h["classes"].items():
                        mix[c] = mix.get(c, 0) + h["value"] * w
            if "return_pct" in ov and "vol_pct" in ov:
                r, v, basis = float(ov["return_pct"]), float(ov["vol_pct"]), "your assumption"
            elif mix:
                r, v = mix_assumption(mix, s["class_assumptions"], s["correlation"]); basis = "mix of the linked accounts"
            else:
                r, v = _glide(months / 12, s["glide"]); basis = f"glide path for {months / 12:.1f} years left"
            sim = simulate(g["current"], monthly, months, r, v, paths=s["paths"], target=target)
            conf = s["confidence_pct"] / 100
            row["projection"] = {"kind": "save", "return_pct": r, "vol_pct": v, "basis": basis, **sim,
                                 "confidence_pct": s["confidence_pct"],
                                 "required_monthly": required_monthly(g["current"], months, r, v, target, conf),
                                 "on_track": sim["probability"] >= conf}
        else:
            row["projection"] = {"kind": "none", "reason": "set a target amount and date to project this goal"
                                 if g["kind"] != "reserve" else "covered by the runway projection"}
        out.append(row)
    return out


def retirement(conn: sqlite3.Connection, cfg: Config, today: date | None = None) -> dict[str, Any]:
    from .allocation import allocation
    from .portfolio_settings import account_registry, get_settings as pf_settings
    from .runway import burn_rate
    s = get_settings(conn)
    r = s["retirement"]
    alloc = allocation(conn, cfg)
    reg = {a["id"]: a for a in account_registry(conn, pf_settings(conn, cfg))}
    mix: dict[str, float] = {}
    assets = 0.0
    hair = 1 - float(r.get("crypto_haircut_pct") or 0) / 100
    for h in alloc["holdings"]:
        a = reg.get(h["account_id"])
        if not a or a["role"] in ("reserve", "earmarked", "excluded") or a["asset_class"] not in r["include_classes"]:
            continue
        v = h["value"] * (hair if a["asset_class"] == "crypto" else 1)
        assets += v
        for c, w in h["classes"].items():
            mix[c] = mix.get(c, 0) + v * w
    burn = burn_rate(conn, cfg, today or date.today())
    spend_default = round((burn["spending"] + burn.get("loan_payments", 0)) * 12, -3)
    spend = float(r["annual_spend"] or spend_default)
    ret, vol = mix_assumption(mix, s["class_assumptions"], s["correlation"]) if mix else (6.0, 12.0)
    real = round(ret - s["inflation_pct"], 2)
    base = {"assets": round(assets), "mix": {k: round(v) for k, v in sorted(mix.items(), key=lambda kv: -kv[1])},
            "return_pct": ret, "real_return_pct": real, "vol_pct": vol, "annual_spend": spend,
            "annual_spend_source": "your setting" if r["annual_spend"] else "12 x current burn from the ledger",
            "settings": r, "inflation_pct": s["inflation_pct"],
            "four_pct_spend": round(assets * 0.04), "needed_at_4pct": round(spend / 0.04)}
    if not r.get("current_age"):
        return {**base, "ready": False, "reason": "enter your current age to run the retirement model"}
    age, ra, ea = int(r["current_age"]), int(r["retire_age"]), int(r["end_age"])
    months = (ea - age) * 12
    schedule = []
    for m in range(months):
        a_now = age + m / 12
        if a_now < ra:
            schedule.append(float(r["annual_contribution"] or 0) / 12)
        else:
            other = float(r["other_income"] or 0) if a_now >= float(r["other_income_age"] or 67) else 0.0
            schedule.append(-(spend - other) / 12)
    sim = simulate(assets, 0, months, real, vol, paths=s["paths"], schedule=schedule)      # real (today's) dollars
    at_ret = next((p for p in sim["series"] if p["month"] >= max(ra - age, 0) * 12), sim["series"][-1])
    series = [{"age": age + p["month"] // 12, **{k: p[k] for k in ("p10", "p50", "p90")}} for p in sim["series"]]
    return {**base, "ready": True, "success_probability": round(1 - sim["depleted_probability"], 3),
            "at_retirement": {"age": max(ra, age), **{k: at_ret[k] for k in ("p10", "p50", "p90")}},
            "series": series, "note": "All figures in today's dollars (returns are net of inflation)."}


def all_projections(conn: sqlite3.Connection, cfg: Config, today: date | None = None) -> dict[str, Any]:
    return {"goals": goal_projections(conn, cfg, today), "retirement": retirement(conn, cfg, today),
            "settings": get_settings(conn)}
