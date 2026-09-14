"""Portfolio settings (editable in the app) and the account registry.

Settings live in the ledger's ``settings`` table under ``portfolio``; ``config.portfolio``
only seeds them. The registry tells the rest of Phase F what each account is for
(reserve / core / thesis / earmarked), how it is taxed and what can be traded in it.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..config import Config, KIND_CLASS
from ..db import now_iso

KEY = "portfolio"
CLASSES = ["us_equity", "intl_equity", "em_equity", "bonds", "gold", "btc", "eth", "other_crypto", "cash", "other"]
CLASS_LABEL = {"us_equity": "US equity", "intl_equity": "International equity", "em_equity": "Emerging markets",
               "bonds": "Bonds", "gold": "Gold", "btc": "Bitcoin", "eth": "Ether", "other_crypto": "Other crypto",
               "cash": "Cash", "other": "Other"}
ROLES = ("reserve", "core", "thesis", "earmarked", "excluded")
TRADABILITY = ("open", "menu", "manual", "cash", "locked")
TAX = ("taxable", "tax_deferred", "tax_free", "tax_free_medical", "tax_free_education", "kiddie", "none")

_ROLE_BY_KIND = {"checking": "reserve", "savings": "reserve", "money_market": "reserve", "cd": "reserve",
                 "cash_mgmt": "reserve", "e529": "earmarked", "custodial": "earmarked", "deferred_comp": "earmarked",
                 "real_estate": "excluded", "vehicle": "excluded", "other": "excluded"}
_TAX_BY_KIND = {"retirement_401k": "tax_deferred", "ira": "tax_deferred", "deferred_comp": "tax_deferred",
                "roth_401k": "tax_free", "roth_ira": "tax_free", "hsa": "tax_free_medical",
                "e529": "tax_free_education", "custodial": "kiddie"}
_TRADE_BY_KIND = {"retirement_401k": "menu", "deferred_comp": "menu", "crypto_wallet": "manual",
                  "crypto_exchange": "manual", "checking": "cash", "savings": "cash", "money_market": "cash",
                  "cd": "cash", "cash_mgmt": "cash", "real_estate": "locked", "vehicle": "locked", "other": "locked"}


def defaults(cfg: Config) -> dict[str, Any]:
    p = cfg.portfolio
    return {"thesis_cap_pct": p.thesis_cap_pct, "drift_band_pct": p.drift_band_pct,
            "crypto_in_policy": p.crypto_in_policy, "never_sell": list(p.never_sell), "policy": dict(p.policy),
            "exposures": dict(p.exposures), "account_roles": dict(p.account_roles),
            "benchmarks": list(p.benchmarks), "macro_series": list(p.macro_series)}


def get_settings(conn: sqlite3.Connection, cfg: Config) -> dict[str, Any]:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (KEY,)).fetchone()
    out = defaults(cfg)
    if row:
        out.update(json.loads(row["value"]) or {})
    return out


def validate(patch: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "thesis_cap_pct" in patch:
        v = float(patch["thesis_cap_pct"])
        if not 0 <= v <= 100:
            raise ValueError("thesis_cap_pct must be between 0 and 100")
        out["thesis_cap_pct"] = v
    if "drift_band_pct" in patch:
        v = float(patch["drift_band_pct"])
        if not 0 < v <= 50:
            raise ValueError("drift_band_pct must be between 0 and 50")
        out["drift_band_pct"] = v
    if "crypto_in_policy" in patch:
        out["crypto_in_policy"] = bool(patch["crypto_in_policy"])
    if "never_sell" in patch:
        out["never_sell"] = sorted({str(x).strip().upper() for x in patch["never_sell"] if str(x).strip()})
    if "policy" in patch:
        pol = {k: float(v) for k, v in (patch["policy"] or {}).items() if v not in (None, "")}
        bad = [k for k in pol if k not in CLASSES]
        if bad:
            raise ValueError(f"unknown policy classes: {', '.join(bad)}; use {', '.join(CLASSES)}")
        if any(v < 0 for v in pol.values()):
            raise ValueError("policy weights must be >= 0")
        total = sum(pol.values())
        if pol and abs(total - 100) > 0.5:
            raise ValueError(f"policy weights sum to {total:g}, not 100")
        out["policy"] = pol
    if "exposures" in patch:
        exp = {}
        for sym, m in (patch["exposures"] or {}).items():
            m = {k: float(v) for k, v in (m or {}).items()}
            bad = [k for k in m if k not in CLASSES]
            if bad:
                raise ValueError(f"unknown exposure classes for {sym}: {', '.join(bad)}")
            if m and abs(sum(m.values()) - 1) > 0.01:
                raise ValueError(f"exposure weights for {sym} must sum to 1")
            exp[str(sym).strip()] = m
        out["exposures"] = exp
    if "account_roles" in patch:
        roles = {}
        for aid, r in (patch["account_roles"] or {}).items():
            r = dict(r or {})
            if r.get("role") and r["role"] not in ROLES:
                raise ValueError(f"role must be one of {', '.join(ROLES)}")
            if r.get("tradability") and r["tradability"] not in TRADABILITY:
                raise ValueError(f"tradability must be one of {', '.join(TRADABILITY)}")
            if r.get("tax_treatment") and r["tax_treatment"] not in TAX:
                raise ValueError(f"tax_treatment must be one of {', '.join(TAX)}")
            if "restrictions" in r:
                r["restrictions"] = sorted({str(x) for x in (r["restrictions"] or [])})
            roles[aid] = {k: v for k, v in r.items() if v not in (None, "", [])}
        out["account_roles"] = roles
    for k in ("benchmarks", "macro_series"):
        if k in patch:
            out[k] = sorted({str(x).strip().upper() if k == "benchmarks" else str(x).strip() for x in patch[k] if str(x).strip()})
    return out


def save_settings(conn: sqlite3.Connection, cfg: Config, patch: dict[str, Any]) -> dict[str, Any]:
    cur = get_settings(conn, cfg)
    cur.update(validate(patch))
    conn.execute("BEGIN")
    conn.execute("INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
                 " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                 (KEY, json.dumps(cur), now_iso()))
    conn.execute("COMMIT")
    return cur


def _override_for(account: dict[str, Any], roles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if account["id"] in roles:
        return roles[account["id"]]
    name = (account["name"] or "").lower()
    for key, r in roles.items():
        if not key.startswith("acc_") and key.lower() in name:
            return r
    return {}


def account_registry(conn: sqlite3.Connection, settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Every active account with its role, tax treatment, tradability and latest balance."""
    from ..ledger.accounts import list_accounts
    out = []
    for a in list_accounts(conn, active_only=True):
        kind = a["kind"]
        if a["is_liability"]:
            continue
        ov = _override_for(a, settings.get("account_roles") or {})
        entry = {"id": a["id"], "name": a["name"], "kind": kind, "institution": a["institution"],
                 "asset_class": KIND_CLASS.get(kind, "other"), "balance": a.get("latest_balance") or 0.0,
                 "balance_as_of": a.get("balance_as_of"),
                 "role": ov.get("role") or _ROLE_BY_KIND.get(kind, "core"),
                 "tax_treatment": ov.get("tax_treatment") or _TAX_BY_KIND.get(kind, "taxable"),
                 "tradability": ov.get("tradability") or _TRADE_BY_KIND.get(kind, "open"),
                 "restrictions": ov.get("restrictions") or ([] if kind not in ("retirement_401k", "roth_401k")
                                                            else ["no_short", "no_margin", "no_options"]),
                 "overridden": bool(ov)}
        out.append(entry)
    return out
