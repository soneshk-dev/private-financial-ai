"""Positions, allocation, crypto and the Aave health factor."""
from __future__ import annotations

import sqlite3
from typing import Any

# Aave V3 Ethereum liquidation thresholds (Jan 2026). Default 0.75 for unknowns.
LIQ_THRESHOLDS = {"WBTC": 0.78, "RETH": 0.79, "WETH": 0.83, "ETH": 0.83, "USDC": 0.76, "DAI": 0.77,
                  "USDT": 0.76, "GHO": 0.0, "WSTETH": 0.81, "CBBTC": 0.78}


def _clean(symbol: str) -> str:
    s = symbol
    for p in ("variableDebtEth", "stableDebtEth", "aEth", "variableDebt", "stableDebt"):
        if s.startswith(p):
            s = s[len(p):]
    return s.upper()


def positions(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("""
        SELECT p.*, a.name AS account_name, a.kind AS account_kind, a.institution, a.entity
        FROM positions_latest p JOIN accounts a ON a.id = p.account_id
        WHERE a.is_active = 1 ORDER BY a.kind, a.name, p.value DESC""").fetchall()
    by_account: dict[str, dict] = {}
    alloc: dict[str, float] = {}
    total = cost = 0.0
    for r in rows:
        acct = by_account.setdefault(r["account_id"], {"account_id": r["account_id"], "name": r["account_name"],
                                                       "kind": r["account_kind"], "institution": r["institution"],
                                                       "as_of": r["as_of"], "value": 0.0, "positions": []})
        acct["value"] += r["value"]
        acct["positions"].append({k: r[k] for k in ("key", "symbol", "description", "quantity", "price", "value",
                                                     "cost_basis", "asset_class")})
        alloc[r["asset_class"] or "other"] = alloc.get(r["asset_class"] or "other", 0.0) + r["value"]
        total += r["value"]
        cost += r["cost_basis"] or 0
    for a in by_account.values():
        a["value"] = round(a["value"], 2)
    return {"total": round(total, 2), "cost_basis_known": round(cost, 2),
            "allocation": {k: round(v, 2) for k, v in sorted(alloc.items(), key=lambda kv: -kv[1])},
            "accounts": list(by_account.values())}


def crypto(conn: sqlite3.Connection) -> dict[str, Any]:
    wallets = conn.execute("SELECT a.id, a.name, a.source, a.meta, b.balance, b.as_of FROM accounts a"
                           " LEFT JOIN (SELECT account_id, balance, as_of FROM balances_daily bd WHERE as_of ="
                           " (SELECT MAX(as_of) FROM balances_daily WHERE account_id = bd.account_id)) b ON b.account_id = a.id"
                           " WHERE a.is_active = 1 AND a.kind IN ('crypto_wallet','crypto_exchange')").fetchall()
    defi = conn.execute("SELECT * FROM defi_positions_latest ORDER BY protocol, meta_type, value DESC").fetchall()
    protocols: dict[str, dict] = {}
    for d in defi:
        p = protocols.setdefault(d["protocol"], {"protocol": d["protocol"], "slug": d["protocol_slug"],
                                                 "network": d["network"], "supplied": [], "borrowed": [], "claimable": [],
                                                 "net": 0.0})
        entry = {"symbol": d["symbol"], "quantity": d["quantity"], "value": d["value"], "price": d["price"]}
        if d["meta_type"] == "BORROWED":
            p["borrowed"].append(entry); p["net"] -= d["value"]
        elif d["meta_type"] == "CLAIMABLE":
            p["claimable"].append(entry); p["net"] += d["value"]
        else:
            p["supplied"].append(entry); p["net"] += d["value"]
    return {"wallets": [dict(w) for w in wallets], "total": round(sum((w["balance"] or 0) for w in wallets), 2),
            "protocols": list(protocols.values()), "aave": aave_health(conn)}


def aave_health(conn: sqlite3.Connection, slug: str = "aave-v3") -> dict[str, Any] | None:
    rows = conn.execute("SELECT meta_type, symbol, quantity, value FROM defi_positions_latest WHERE protocol_slug = ?",
                        (slug,)).fetchall()
    if not rows:
        return None
    coll = debt = weighted = 0.0
    coll_b: dict[str, float] = {}
    debt_b: dict[str, float] = {}
    btc_usd = btc_qty = 0.0
    for meta_type, symbol, qty, usd in rows:
        if usd < 0.01:
            continue
        s = _clean(symbol)
        if meta_type == "BORROWED":
            debt += usd
            debt_b[s] = debt_b.get(s, 0) + usd
        elif meta_type == "SUPPLIED":
            coll += usd
            lt = LIQ_THRESHOLDS.get(s, 0.75)
            weighted += usd * lt
            coll_b[s] = coll_b.get(s, 0) + usd
            if "BTC" in s:
                btc_usd += usd
                btc_qty += qty or 0
    hf = (weighted / debt) if debt > 0 else float("inf")
    status = "healthy" if hf >= 2 else "moderate" if hf >= 1.5 else "warning" if hf >= 1.3 else "danger"
    liq_btc = None
    btc_lt = LIQ_THRESHOLDS["WBTC"]
    if btc_qty > 0 and debt > 0:
        other = weighted - btc_usd * btc_lt
        liq_btc = (debt - other) / (btc_qty * btc_lt)
    return {"health_factor": round(min(hf, 99.99), 2), "status": status, "collateral": round(coll, 0),
            "debt": round(debt, 0), "weighted_collateral": round(weighted, 0),
            "liquidation_price_btc": round(liq_btc, 0) if liq_btc else None,
            "collateral_breakdown": {k: round(v) for k, v in coll_b.items()},
            "debt_breakdown": {k: round(v) for k, v in debt_b.items()}}
