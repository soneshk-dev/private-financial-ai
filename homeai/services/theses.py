"""Short/mid-term theses: a view, a horizon, a budget inside the thesis cap, legs that express it,
exit rules and kill metrics checked against market data."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from typing import Any

from ..config import Config
from ..db import now_iso
from .market import latest_price, macro_value, price_history

STATUSES = ("draft", "active", "closed")
_FIELDS = ("name", "view", "status", "conviction", "budget_pct", "horizon_start", "horizon_end", "benchmark",
           "exit_rules", "kill_metrics", "notes")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "thesis"


def _clean(fields: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in fields.items() if k in _FIELDS and v is not None}
    if "status" in out and out["status"] not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    if "conviction" in out:
        out["conviction"] = max(1, min(3, int(out["conviction"])))
    if "budget_pct" in out:
        out["budget_pct"] = float(out["budget_pct"])
        if not 0 <= out["budget_pct"] <= 100:
            raise ValueError("budget_pct is a share of the thesis cap, 0-100")
    for k in ("horizon_start", "horizon_end"):
        if k in out:
            date.fromisoformat(out[k])
    if "benchmark" in out:
        out["benchmark"] = str(out["benchmark"]).upper().strip() or None
    if "kill_metrics" in out:
        km = out["kill_metrics"] if isinstance(out["kill_metrics"], list) else json.loads(out["kill_metrics"])
        for m in km:
            if m.get("op") not in (">", "<") or "series" not in m or "level" not in m:
                raise ValueError("kill metric needs series, op ('>' or '<') and level")
            m["level"] = float(m["level"])
        out["kill_metrics"] = json.dumps(km)
    return out


def save_thesis(conn: sqlite3.Connection, slug: str | None = None, **fields: Any) -> str:
    f = _clean(fields)
    ts = now_iso()
    if slug and conn.execute("SELECT 1 FROM theses WHERE slug = ?", (slug,)).fetchone():
        if f.get("status") == "closed":
            f["closed_at"] = ts
        if f:
            sets = ", ".join(f"{k} = ?" for k in f)
            conn.execute(f"UPDATE theses SET {sets}, updated_at = ? WHERE slug = ?", (*f.values(), ts, slug))
        return slug
    if not f.get("name") or not f.get("view"):
        raise ValueError("a new thesis needs a name and a view")
    slug = slug or slugify(f["name"])
    base, i = slug, 2
    while conn.execute("SELECT 1 FROM theses WHERE slug = ?", (slug,)).fetchone():
        slug = f"{base}-{i}"; i += 1
    f.setdefault("horizon_start", date.today().isoformat())
    cols = ["slug", *f.keys(), "created_at", "updated_at"]
    conn.execute(f"INSERT INTO theses ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", (slug, *f.values(), ts, ts))
    return slug


def save_leg(conn: sqlite3.Connection, thesis_slug: str, leg_id: int | None = None, **fields: Any) -> int:
    if not conn.execute("SELECT 1 FROM theses WHERE slug = ?", (thesis_slug,)).fetchone():
        raise KeyError(thesis_slug)
    allowed = ("symbol", "direction", "target_weight", "account_id", "opened_at", "closed_at", "entry_price", "quantity", "notes")
    f = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "symbol" in f:
        f["symbol"] = str(f["symbol"]).upper().strip()
    if f.get("direction") and f["direction"] not in ("long", "underweight"):
        raise ValueError("direction is 'long' or 'underweight' (no shorting in these accounts)")
    if f.get("account_id") and not conn.execute("SELECT 1 FROM accounts WHERE id = ?", (f["account_id"],)).fetchone():
        raise ValueError("unknown account")
    ts = now_iso()
    if leg_id:
        if f:
            sets = ", ".join(f"{k} = ?" for k in f)
            conn.execute(f"UPDATE thesis_legs SET {sets}, updated_at = ? WHERE id = ? AND thesis_slug = ?", (*f.values(), ts, leg_id, thesis_slug))
        return leg_id
    if not f.get("symbol"):
        raise ValueError("a leg needs a symbol")
    cols = ["thesis_slug", *f.keys(), "updated_at"]
    cur = conn.execute(f"INSERT INTO thesis_legs ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", (thesis_slug, *f.values(), ts))
    return cur.lastrowid


def delete_leg(conn: sqlite3.Connection, thesis_slug: str, leg_id: int) -> None:
    conn.execute("DELETE FROM thesis_legs WHERE id = ? AND thesis_slug = ?", (leg_id, thesis_slug))


def _metric_value(conn: sqlite3.Connection, series: str) -> float | None:
    if series.startswith("price:"):
        p = latest_price(conn, series.split(":", 1)[1].upper())
        return p["close"] if p else None
    return macro_value(conn, series)


def _price_on(conn: sqlite3.Connection, symbol: str, day: str) -> float | None:
    r = conn.execute("SELECT close FROM prices_daily WHERE symbol = ? AND as_of <= ? ORDER BY as_of DESC LIMIT 1", (symbol, day)).fetchone()
    if r:
        return r["close"]
    r = conn.execute("SELECT close FROM prices_daily WHERE symbol = ? ORDER BY as_of LIMIT 1", (symbol,)).fetchone()
    return r["close"] if r else None


def _leg_view(conn: sqlite3.Connection, leg: sqlite3.Row) -> dict[str, Any]:
    d = dict(leg)
    px = latest_price(conn, d["symbol"])
    qty = d["quantity"]
    held = None
    if d["account_id"]:
        held = conn.execute("SELECT quantity, value, cost_basis, price FROM positions_latest WHERE account_id = ? AND upper(symbol) = ?",
                            (d["account_id"], d["symbol"])).fetchone()
        acct = conn.execute("SELECT name FROM accounts WHERE id = ?", (d["account_id"],)).fetchone()
        d["account_name"] = acct["name"] if acct else None
    if qty is None and held:
        qty = held["quantity"]
        d["quantity_source"] = "held position"
    price = px["close"] if px else (held["price"] if held else None)
    d["price"], d["price_as_of"] = price, (px["as_of"] if px else None)
    entry = d["entry_price"]
    if entry is None and held and held["cost_basis"] and held["quantity"]:
        entry = held["cost_basis"] / held["quantity"]
        d["entry_source"] = "cost basis"
    d["entry_price_used"] = entry
    d["value"] = round(qty * price, 2) if (qty and price and d["direction"] == "long" and not d["closed_at"]) else 0.0
    d["pnl"] = round((price - entry) * qty, 2) if (qty and price and entry and d["direction"] == "long") else None
    d["return_pct"] = round((price / entry - 1) * 100, 1) if (price and entry) else None
    return d


def list_theses(conn: sqlite3.Connection, cfg: Config, include_closed: bool = False, today: date | None = None,
                thesis_cap: float | None = None) -> list[dict[str, Any]]:
    today = today or date.today()
    if thesis_cap is None:
        from .allocation import allocation
        thesis_cap = allocation(conn, cfg)["thesis_cap"]
    out = []
    sql = "SELECT * FROM theses" + ("" if include_closed else " WHERE status != 'closed'") + " ORDER BY status, horizon_end"
    for t in conn.execute(sql).fetchall():
        d = dict(t)
        d["kill_metrics"] = json.loads(d["kill_metrics"] or "[]")
        for m in d["kill_metrics"]:
            v = _metric_value(conn, m["series"])
            m["value"] = v
            m["breached"] = (v is not None) and (v > m["level"] if m["op"] == ">" else v < m["level"])
            m["distance_pct"] = round((m["level"] / v - 1) * 100, 1) if v else None
        legs = [_leg_view(conn, l) for l in conn.execute("SELECT * FROM thesis_legs WHERE thesis_slug = ? ORDER BY id", (d["slug"],))]
        d["legs"] = legs
        d["budget"] = round(thesis_cap * d["budget_pct"] / 100, 0)
        d["deployed"] = round(sum(l["value"] for l in legs), 0)
        pnls = [l["pnl"] for l in legs if l["pnl"] is not None and not l["closed_at"]]
        d["pnl"] = round(sum(pnls), 0) if pnls else None
        d["over_budget"] = d["deployed"] > d["budget"] > 0
        if d["horizon_start"] and d["horizon_end"]:
            a, b = date.fromisoformat(d["horizon_start"]), date.fromisoformat(d["horizon_end"])
            d["horizon_pct"] = round(min(max((today - a).days / max((b - a).days, 1), 0), 1) * 100)
            d["days_left"] = (b - today).days
            d["expired"] = today > b and d["status"] == "active"
        if d["benchmark"] and d["horizon_start"]:
            p0, p1 = _price_on(conn, d["benchmark"], d["horizon_start"]), latest_price(conn, d["benchmark"])
            d["benchmark_return_pct"] = round((p1["close"] / p0 - 1) * 100, 1) if (p0 and p1) else None
        basis = sum((l["entry_price_used"] or 0) * (l["quantity"] or 0) for l in legs if l["pnl"] is not None)
        d["return_pct"] = round(d["pnl"] / basis * 100, 1) if (d["pnl"] is not None and basis) else None
        d["kill_breached"] = any(m["breached"] for m in d["kill_metrics"])
        out.append(d)
    return out


def budget_status(conn: sqlite3.Connection, cfg: Config, alloc: dict[str, Any] | None = None) -> dict[str, Any]:
    from .allocation import allocation
    alloc = alloc or allocation(conn, cfg)
    ths = [t for t in list_theses(conn, cfg, thesis_cap=alloc["thesis_cap"]) if t["status"] == "active"]
    deployed = sum(t["deployed"] for t in ths)
    return {"cap": alloc["thesis_cap"], "cap_pct": alloc["settings"]["thesis_cap_pct"], "deployed": round(deployed, 0),
            "allocated_pct_of_cap": round(sum(t["budget_pct"] for t in ths), 1),
            "remaining": round(alloc["thesis_cap"] - deployed, 0)}


def alerts(conn: sqlite3.Connection, cfg: Config, today: date | None = None) -> list[dict[str, str]]:
    out = []
    for t in list_theses(conn, cfg, today=today):
        if t["status"] != "active":
            continue
        for m in t["kill_metrics"]:
            if m["breached"]:
                out.append({"key": f"thesis_kill_{t['slug']}_{m['series']}",
                            "text": f"Thesis '{t['name']}': kill metric hit, {m['series']} {m['op']} {m['level']:g} (now {m['value']:g})"})
        if t.get("expired"):
            out.append({"key": f"thesis_expired_{t['slug']}", "text": f"Thesis '{t['name']}' passed its horizon ({t['horizon_end']}): close or extend it"})
        elif t.get("days_left") is not None and 0 <= t["days_left"] <= 30:
            out.append({"key": f"thesis_ending_{t['slug']}", "text": f"Thesis '{t['name']}' ends in {t['days_left']} days"})
        if t["over_budget"]:
            out.append({"key": f"thesis_budget_{t['slug']}", "text": f"Thesis '{t['name']}' is over budget: ${t['deployed']:,.0f} of ${t['budget']:,.0f}"})
    return out
