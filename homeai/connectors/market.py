"""Market data without accounts or API keys.

* Nasdaq's public quote API: daily closes for US-listed stocks and ETFs (held symbols,
  benchmarks, thesis legs).
* US Treasury: the daily par yield curve (3m/2y/10y/30y).
* EIA: Cushing WTI spot (dollars per barrel), from the public history page.
* CoinGecko: BTC and ETH spot.

Everything lands in ``prices_daily`` / ``macro_daily``; nothing here needs a secret.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import time
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from ..config import Config
from ..db import now_iso
from .base import SyncResult, store_raw

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
NASDAQ = "https://api.nasdaq.com/api/quote/{symbol}/historical"
TREASURY = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
            "{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv")
EIA_WTI = "https://www.eia.gov/dnav/pet/hist/RWTCd.htm"
COINGECKO = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd"
TREASURY_SERIES = {"ust_3m": "3 Mo", "ust_2y": "2 Yr", "ust_10y": "10 Yr", "ust_30y": "30 Yr"}
_TICKER = re.compile(r"^[A-Z]{1,5}$")
_MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


class MarketConnector:
    name = "market"

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def configured(self) -> bool:
        return True

    # --- parsing (pure) --------------------------------------------------------
    @staticmethod
    def parse_nasdaq(payload: dict[str, Any]) -> list[tuple[str, float]]:
        rows = (((payload or {}).get("data") or {}).get("tradesTable") or {}).get("rows") or []
        out = []
        for r in rows:
            try:
                d = datetime.strptime(r["date"], "%m/%d/%Y").date().isoformat()
                close = float(str(r["close"]).replace("$", "").replace(",", ""))
            except (KeyError, ValueError, TypeError):
                continue
            out.append((d, close))
        return out

    @staticmethod
    def parse_treasury(text: str) -> dict[str, list[tuple[str, float]]]:
        out: dict[str, list[tuple[str, float]]] = {k: [] for k in TREASURY_SERIES}
        for row in csv.DictReader(io.StringIO(text)):
            try:
                d = datetime.strptime(row["Date"], "%m/%d/%Y").date().isoformat()
            except (KeyError, ValueError):
                continue
            for series, col in TREASURY_SERIES.items():
                v = (row.get(col) or "").strip()
                if v:
                    try:
                        out[series].append((d, float(v)))
                    except ValueError:
                        pass
        return out

    @staticmethod
    def parse_eia(html: str) -> list[tuple[str, float]]:
        """Rows look like: <td class='B6'>2026 Sep- 7 to Sep-11</td> then five <td class='B3'> values (Mon..Fri)."""
        out = []
        for m in re.finditer(r"<td class='B6'>\s*(?:&nbsp;)*\s*(\d{4}) ([A-Z][a-z]{2})-\s*(\d{1,2}) to [A-Z][a-z]{2}-\s*\d{1,2}</td>"
                             r"((?:\s*<td class='B3'>[^<]*</td>){5})", html):
            year, mon, day, cells = int(m.group(1)), _MONTHS.get(m.group(2)), int(m.group(3)), m.group(4)
            if not mon:
                continue
            start = date(year, mon, day)
            vals = re.findall(r"<td class='B3'>([^<]*)</td>", cells)
            for i, v in enumerate(vals):
                v = v.strip()
                if v:
                    try:
                        out.append(((start + timedelta(days=i)).isoformat(), float(v)))
                    except ValueError:
                        pass
        return out

    # --- fetching ----------------------------------------------------------------
    def _client(self) -> httpx.Client:
        return httpx.Client(headers={"User-Agent": UA, "Accept": "application/json, text/plain, */*"},
                            timeout=30, follow_redirects=True)

    def _nasdaq(self, client: httpx.Client, symbol: str, asset_class: str, since: str) -> dict[str, Any]:
        r = client.get(NASDAQ.format(symbol=symbol), params={"assetclass": asset_class, "fromdate": since, "limit": 40})
        r.raise_for_status()
        return r.json()

    def fetch_symbol(self, conn: sqlite3.Connection, symbol: str, days: int = 200) -> int:
        """On-demand history for one symbol (used when analysing something not yet held)."""
        symbol = symbol.upper()
        if not _TICKER.match(symbol):
            return 0
        classes = _load_classes(conn)
        since = (date.today() - timedelta(days=days)).isoformat()
        with self._client() as client:
            for ac in ([classes[symbol]] if symbol in classes else []) + [c for c in ("etf", "stocks") if c != classes.get(symbol)]:
                r = client.get(NASDAQ.format(symbol=symbol), params={"assetclass": ac, "fromdate": since, "limit": days})
                r.raise_for_status()
                rows = self.parse_nasdaq(r.json())
                if rows:
                    classes[symbol] = ac
                    _save_classes(conn, classes)
                    return _upsert_prices(conn, symbol, rows, "nasdaq")
        return 0

    def symbols_to_price(self, conn: sqlite3.Connection, settings: dict[str, Any]) -> list[str]:
        syms = set(settings.get("benchmarks") or [])
        for r in conn.execute("SELECT DISTINCT p.symbol FROM positions_latest p JOIN accounts a ON a.id = p.account_id"
                              " WHERE a.is_active = 1 AND p.symbol IS NOT NULL AND a.kind NOT IN ('crypto_wallet','crypto_exchange')"):
            syms.add(r["symbol"])
        for r in conn.execute("SELECT DISTINCT symbol FROM thesis_legs WHERE closed_at IS NULL"):
            syms.add(r["symbol"])
        return sorted(s for s in syms if _TICKER.match(s or ""))

    def sync(self, conn: sqlite3.Connection, cfg: Config, as_of: str) -> SyncResult:
        from ..services.portfolio_settings import get_settings
        result = SyncResult(self.name)
        settings = get_settings(conn, cfg)
        since = (date.today() - timedelta(days=21)).isoformat()
        classes = _load_classes(conn)
        n_prices = n_macro = 0
        errors: list[str] = []
        with self._client() as client:
            for sym in self.symbols_to_price(conn, settings):
                got = None
                for ac in ([classes[sym]] if sym in classes else []) + [c for c in ("etf", "stocks") if c != classes.get(sym)]:
                    try:
                        payload = self._nasdaq(client, sym, ac, since)
                    except Exception as e:  # noqa: BLE001
                        errors.append(f"{sym}: {e!r}"); break
                    rows = self.parse_nasdaq(payload)
                    if rows:
                        got = rows; classes[sym] = ac; break
                    time.sleep(0.2)
                if got:
                    n_prices += _upsert_prices(conn, sym, got, "nasdaq")
                time.sleep(0.3)
            want = set(settings.get("macro_series") or [])
            if want & set(TREASURY_SERIES):
                try:
                    r = client.get(TREASURY.format(year=date.today().year)); r.raise_for_status()
                    for series, rows in self.parse_treasury(r.text).items():
                        if series in want:
                            n_macro += _upsert_macro(conn, series, rows[:40], "treasury")
                except Exception as e:  # noqa: BLE001
                    errors.append(f"treasury: {e!r}")
            if "wti_usd" in want:
                try:
                    r = client.get(EIA_WTI); r.raise_for_status()
                    n_macro += _upsert_macro(conn, "wti_usd", self.parse_eia(r.text)[-40:], "eia")
                except Exception as e:  # noqa: BLE001
                    errors.append(f"eia: {e!r}")
            if want & {"btc_usd", "eth_usd"}:
                try:
                    r = client.get(COINGECKO); r.raise_for_status()
                    j = r.json()
                    store_raw(conn, self.name, "coingecko", None, j)
                    if "btc_usd" in want and j.get("bitcoin"):
                        n_macro += _upsert_macro(conn, "btc_usd", [(as_of, float(j["bitcoin"]["usd"]))], "coingecko")
                    if "eth_usd" in want and j.get("ethereum"):
                        n_macro += _upsert_macro(conn, "eth_usd", [(as_of, float(j["ethereum"]["usd"]))], "coingecko")
                except Exception as e:  # noqa: BLE001
                    errors.append(f"coingecko: {e!r}")
        _save_classes(conn, classes)
        result.rows_written = n_prices + n_macro
        result.detail = {"prices": n_prices, "macro": n_macro, "symbols": len(classes), "errors": errors[:10]}
        if errors and not (n_prices or n_macro):
            result.ok = False
            result.error = "; ".join(errors[:3])
        return result


def _upsert_prices(conn: sqlite3.Connection, symbol: str, rows: list[tuple[str, float]], source: str) -> int:
    ts = now_iso()
    conn.executemany("INSERT INTO prices_daily (symbol, as_of, close, source, captured_at) VALUES (?,?,?,?,?)"
                     " ON CONFLICT(symbol, as_of) DO UPDATE SET close = excluded.close, captured_at = excluded.captured_at",
                     [(symbol, d, c, source, ts) for d, c in rows])
    return len(rows)


def _upsert_macro(conn: sqlite3.Connection, series: str, rows: list[tuple[str, float]], source: str) -> int:
    ts = now_iso()
    conn.executemany("INSERT INTO macro_daily (series, as_of, value, source, captured_at) VALUES (?,?,?,?,?)"
                     " ON CONFLICT(series, as_of) DO UPDATE SET value = excluded.value, captured_at = excluded.captured_at",
                     [(series, d, v, source, ts) for d, v in rows])
    return len(rows)


def _load_classes(conn: sqlite3.Connection) -> dict[str, str]:
    row = conn.execute("SELECT value FROM settings WHERE key = 'market_asset_class'").fetchone()
    return json.loads(row["value"]) if row else {}


def _save_classes(conn: sqlite3.Connection, classes: dict[str, str]) -> None:
    conn.execute("INSERT INTO settings (key, value, updated_at) VALUES ('market_asset_class', ?, ?)"
                 " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                 (json.dumps(classes), now_iso()))
