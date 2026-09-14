"""Reads over prices_daily / macro_daily."""
from __future__ import annotations

import sqlite3
from typing import Any

MACRO_LABEL = {"wti_usd": "WTI crude ($/bbl)", "ust_3m": "3-month Treasury (%)", "ust_2y": "2-year Treasury (%)",
               "ust_10y": "10-year Treasury (%)", "ust_30y": "30-year Treasury (%)", "btc_usd": "Bitcoin ($)",
               "eth_usd": "Ether ($)"}


def _series(conn: sqlite3.Connection, table: str, keycol: str, key: str, days: int) -> list[dict[str, Any]]:
    valcol = "close" if table == "prices_daily" else "value"
    rows = conn.execute(f"SELECT as_of, {valcol} AS value FROM {table} WHERE {keycol} = ? ORDER BY as_of DESC LIMIT ?",
                        (key, days)).fetchall()
    return [dict(r) for r in reversed(rows)]


def latest_price(conn: sqlite3.Connection, symbol: str) -> dict[str, Any] | None:
    r = conn.execute("SELECT as_of, close FROM prices_daily WHERE symbol = ? ORDER BY as_of DESC LIMIT 1", (symbol,)).fetchone()
    return dict(r) if r else None


def price_history(conn: sqlite3.Connection, symbol: str, days: int = 60) -> list[dict[str, Any]]:
    return _series(conn, "prices_daily", "symbol", symbol, days)


def macro(conn: sqlite3.Connection, days: int = 30) -> list[dict[str, Any]]:
    """Latest value and change over ~a month for every macro series we hold."""
    out = []
    for (series,) in conn.execute("SELECT DISTINCT series FROM macro_daily ORDER BY series"):
        s = _series(conn, "macro_daily", "series", series, days)
        if not s:
            continue
        first, last = s[0], s[-1]
        out.append({"series": series, "label": MACRO_LABEL.get(series, series), "as_of": last["as_of"],
                    "value": last["value"], "prior": first["value"], "prior_as_of": first["as_of"],
                    "change": round(last["value"] - first["value"], 4), "history": s})
    return out


def macro_value(conn: sqlite3.Connection, series: str) -> float | None:
    r = conn.execute("SELECT value FROM macro_daily WHERE series = ? ORDER BY as_of DESC LIMIT 1", (series,)).fetchone()
    return r["value"] if r else None
