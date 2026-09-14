"""Look-through allocation: every position mapped to a policy class, summed across
accounts and sleeves, compared with the policy targets."""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from ..config import Config
from .portfolio_settings import CLASSES, CLASS_LABEL, account_registry, get_settings

# Symbol → class weights. Extend via settings.exposures (symbol or description substring).
DEFAULT_EXPOSURES: dict[str, dict[str, float]] = {
    "IAU": {"gold": 1}, "GLD": {"gold": 1}, "GLDM": {"gold": 1}, "SGOL": {"gold": 1}, "IAUM": {"gold": 1},
    "IBIT": {"btc": 1}, "FBTC": {"btc": 1}, "BTC": {"btc": 1}, "WBTC": {"btc": 1}, "CBBTC": {"btc": 1}, "BITB": {"btc": 1},
    "ETH": {"eth": 1}, "WETH": {"eth": 1}, "WSTETH": {"eth": 1}, "STETH": {"eth": 1}, "RETH": {"eth": 1}, "ETHA": {"eth": 1},
    "USDC": {"cash": 1}, "USDT": {"cash": 1}, "DAI": {"cash": 1}, "GHO": {"cash": 1}, "USDS": {"cash": 1},
    "VFIAX": {"us_equity": 1}, "VOO": {"us_equity": 1}, "SPY": {"us_equity": 1}, "IVV": {"us_equity": 1},
    "VTI": {"us_equity": 1}, "VTSAX": {"us_equity": 1}, "FXAIX": {"us_equity": 1}, "QQQ": {"us_equity": 1},
    "VTMGX": {"intl_equity": 1}, "VEA": {"intl_equity": 1}, "VXUS": {"intl_equity": 0.75, "em_equity": 0.25},
    "EFA": {"intl_equity": 1}, "IEFA": {"intl_equity": 1}, "VWO": {"em_equity": 1}, "IEMG": {"em_equity": 1},
    "EEM": {"em_equity": 1},
    "BND": {"bonds": 1}, "AGG": {"bonds": 1}, "TLT": {"bonds": 1}, "IEF": {"bonds": 1}, "SHY": {"bonds": 1},
    "BNDX": {"bonds": 1}, "VBTLX": {"bonds": 1}, "EDV": {"bonds": 1}, "TIP": {"bonds": 1}, "GOVT": {"bonds": 1},
    "NODE": {"us_equity": 0.5, "other_crypto": 0.5}, "SOL": {"other_crypto": 1},
}
_NAME_HINTS: list[tuple[re.Pattern, dict[str, float]]] = [
    (re.compile(r"money market|cash reserves|treasury only|fdic|core account|govt mm|\bcash\b", re.I), {"cash": 1}),
    (re.compile(r"emerging|\bem\b", re.I), {"em_equity": 1}),
    (re.compile(r"eafe|developed|international|intl|ex-us|ex us|world ex", re.I), {"intl_equity": 1}),
    (re.compile(r"\bbond|\bbd\b|aggr|treasury|fixed income|\btips\b", re.I), {"bonds": 1}),
    (re.compile(r"gold", re.I), {"gold": 1}),
    (re.compile(r"bitcoin", re.I), {"btc": 1}),
    (re.compile(r"ether(eum)?\b", re.I), {"eth": 1}),
    (re.compile(r"s&p|500|total (stock )?market|russell|smid|small.?cap|mid.?cap|large.?cap|nasdaq|magnificent|equity", re.I),
     {"us_equity": 1}),
]


def classify_position(symbol: str | None, description: str | None, asset_class: str | None,
                      exposures: dict[str, dict[str, float]]) -> tuple[dict[str, float], str]:
    """Return ({class: weight}, how) for a holding. ``how`` is 'user', 'symbol', 'name' or 'class'."""
    sym = (symbol or "").upper().strip()
    desc = description or ""
    for key, m in exposures.items():
        k = key.strip()
        if sym and k.upper() == sym:
            return m, "user"
        if k and not k.isupper() and k.lower() in desc.lower():
            return m, "user"
    if sym in DEFAULT_EXPOSURES:
        return DEFAULT_EXPOSURES[sym], "symbol"
    for pat, m in _NAME_HINTS:
        if pat.search(desc) or (sym and pat.search(sym)):
            return m, "name"
    ac = (asset_class or "").lower()
    if ac == "cash":
        return {"cash": 1}, "class"
    if ac == "bond":
        return {"bonds": 1}, "class"
    if ac == "crypto":
        return {"other_crypto": 1}, "class"
    if ac == "equity" and sym and re.fullmatch(r"[A-Z]{1,5}", sym):
        return {"us_equity": 1}, "equity"          # a plain US ticker: a US-listed common stock
    if ac in ("equity", "etf", "fund"):
        return {"us_equity": 1}, "class"
    return {"other": 1}, "class"


_KIND_CLASS = {"crypto_wallet": {"other_crypto": 1}, "crypto_exchange": {"other_crypto": 1}}


def allocation(conn: sqlite3.Connection, cfg: Config, today: str | None = None) -> dict[str, Any]:
    settings = get_settings(conn, cfg)
    registry = {a["id"]: a for a in account_registry(conn, settings)}
    exposures = settings.get("exposures") or {}
    policy = settings.get("policy") or {}
    pos_rows = conn.execute("SELECT p.*, a.name AS account_name FROM positions_latest p JOIN accounts a ON a.id = p.account_id"
                            " WHERE a.is_active = 1 AND p.value > 0").fetchall()
    have_positions = {r["account_id"] for r in pos_rows}

    by_class: dict[str, float] = {c: 0.0 for c in CLASSES}
    sleeves: dict[str, float] = {"reserve": 0.0, "core": 0.0, "thesis": 0.0, "earmarked": 0.0, "excluded": 0.0}
    holdings: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []

    def add(acct: dict[str, Any], value: float, weights: dict[str, float], how: str, symbol: str | None,
            description: str | None, account_id: str, quantity=None, price=None, cost=None):
        role = acct["role"]
        sleeves[role] += value
        holdings.append({"account_id": account_id, "account_name": acct["name"], "role": role,
                         "tax_treatment": acct["tax_treatment"], "symbol": symbol, "description": description,
                         "value": round(value, 2), "quantity": quantity, "price": price, "cost_basis": cost,
                         "classes": weights, "how": how})
        if role in ("excluded",):
            return
        if role == "reserve" or role == "earmarked":
            return                          # reported as sleeves, not against the policy
        for c, w in weights.items():
            by_class[c] = by_class.get(c, 0.0) + value * w
        if how == "class" and (symbol or description) and value >= 1:
            unknown.append({"symbol": symbol, "description": description, "value": round(value, 2), "account": acct["name"]})

    for r in pos_rows:
        acct = registry.get(r["account_id"])
        if not acct:
            continue
        weights, how = classify_position(r["symbol"], r["description"], r["asset_class"], exposures)
        add(acct, float(r["value"]), weights, how, r["symbol"], r["description"], r["account_id"],
            r["quantity"], r["price"], r["cost_basis"])
    for aid, acct in registry.items():               # balance-only accounts (cash management, exchanges)
        if aid in have_positions or not acct["balance"]:
            continue
        kind = acct["kind"]
        weights = _KIND_CLASS.get(kind) or ({"cash": 1} if acct["asset_class"] == "cash" else {"other": 1})
        add(acct, float(acct["balance"]), weights, "kind", None, acct["name"], aid)

    investable = sleeves["core"] + sleeves["thesis"]
    if not settings.get("crypto_in_policy", True):
        for c in ("btc", "eth", "other_crypto"):
            investable -= by_class.get(c, 0.0)
    rows = []
    for c in CLASSES:
        v = by_class.get(c, 0.0)
        if not settings.get("crypto_in_policy", True) and c in ("btc", "eth", "other_crypto"):
            rows.append({"class": c, "label": CLASS_LABEL[c], "value": round(v, 2), "pct": None, "policy_pct": None,
                         "drift_pct": None, "drift_value": None, "side": True})
            continue
        pct = (v / investable * 100) if investable else 0.0
        target = policy.get(c)
        drift = (pct - target) if target is not None else None
        rows.append({"class": c, "label": CLASS_LABEL[c], "value": round(v, 2), "pct": round(pct, 1),
                     "policy_pct": target, "drift_pct": round(drift, 1) if drift is not None else None,
                     "drift_value": round(drift / 100 * investable, 0) if drift is not None else None,
                     "out_of_band": (abs(drift) > settings["drift_band_pct"]) if drift is not None else False})
    thesis_cap = investable * settings["thesis_cap_pct"] / 100
    return {"as_of": today or (pos_rows[0]["as_of"] if pos_rows else None),
            "investable": round(investable, 2),
            "sleeves": {k: round(v, 2) for k, v in sleeves.items()},
            "thesis_cap": round(thesis_cap, 2), "thesis_used": round(sleeves["thesis"], 2),
            "by_class": rows, "holdings": sorted(holdings, key=lambda h: -h["value"]),
            "unclassified": sorted(unknown, key=lambda u: -u["value"]), "settings": settings,
            "accounts": list(registry.values())}
