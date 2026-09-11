"""Fina.money: Fidelity balances, holdings and transactions (via Fina's aggregator).

Kept until Plaid's Fidelity OAuth connection is approved; then retire.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
from datetime import date, timedelta
from typing import Any

import httpx

from ..config import Config
from ..ledger.accounts import kind_from_name, upsert_account
from ..ledger.balances import record_balance, replace_positions
from ..ledger.classify import compile_rules
from ..ledger.transactions import upsert_transaction
from .base import SyncResult, parse_kv_conf, store_raw

BASE = "https://app.fina.money/api/resource/account"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")

KNOWN_SYMBOLS = {
    "ishares bitcoin trust": "IBIT", "fidelity wise origin bitcoin": "FBTC", "ishares gold trust": "IAU",
    "vanguard 500 index": "VFIAX", "vanguard developed markets": "VTMGX", "vaneck onchain economy": "NODE",
    "galaxy digital": "GLXY", "alphabet inc": "GOOG", "nvidia corp": "NVDA", "apple inc": "AAPL",
    "microsoft corp": "MSFT", "amazon.com inc": "AMZN", "meta platforms": "META", "tesla inc": "TSLA",
    "vanguard bd index": "BND", "vanguard total bond": "BND",
}


def asset_class_from_name(name: str) -> str:
    n = (name or "").lower()
    if "money market" in n or "cash reserves" in n or n in ("cash", "pending activity"):
        return "cash"
    if " etf" in n or n.endswith(" etf") or "ishares" in n or "vaneck" in n:
        return "etf"
    if "fund" in n or "trust" in n or " idx" in n or "index" in n:
        return "fund"
    if "bitcoin" in n or "ether" in n or "crypto" in n:
        return "crypto"
    if " bd " in n or "bond" in n or "treasury" in n:
        return "bond"
    return "equity"


class FinaConnector:
    name = "fina"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.api_key = parse_kv_conf(cfg.secrets_dir / cfg.fina.conf_file).get("FINA_API_KEY")

    def configured(self) -> bool:
        return bool(self.api_key)

    def _get(self, endpoint: str) -> httpx.Response:
        r = httpx.get(f"{BASE}/{endpoint}", headers={"x-api-key": self.api_key}, timeout=60, follow_redirects=True)
        r.raise_for_status()
        return r

    # --- parsing --------------------------------------------------------------
    @staticmethod
    def parse_balances(data: list[dict]) -> list[dict[str, Any]]:
        out = []
        for profile in data or []:
            for b in (profile.get("accounts") or profile.get("balances") or []):
                if b:
                    out.append({"id": b.get("id"), "name": b.get("name"), "balance": b.get("balance"),
                                "available": b.get("available"), "institute": b.get("institute")})
        return out

    @staticmethod
    def parse_transactions(text: str) -> list[dict[str, Any]]:
        """Fina's CSV is headerless. New layout (2026): id,date,description,merchant,account_id,amount,
        category,currency,tag,... Old layout: date,name,merchant,account,amount,category,currency,tag.
        The layout is detected by where the date sits (ids are opaque tokens, not UUIDs)."""
        out = []
        for row in csv.reader(io.StringIO(text)):
            if len(row) < 7:
                continue
            try:
                if len(row) >= 8 and _DATE.match(row[1] or "") and not _DATE.match(row[0] or ""):
                    amount = float(row[5]) if row[5] else 0.0
                    rec = {"id": row[0], "date": row[1][:10], "name": row[2], "merchant": row[3] or None,
                           "account_id": row[4], "amount": amount, "category": row[6] or None,
                           "currency": row[7] or "USD"}
                else:
                    amount = float(row[4]) if row[4] else 0.0
                    rec = {"id": None, "date": row[0][:10], "name": row[1], "merchant": row[2] or None,
                           "account_id": row[3], "amount": amount, "category": row[5] or None,
                           "currency": row[6] or "USD"}
            except (ValueError, TypeError, IndexError):
                continue
            if not rec["id"]:
                rec["id"] = hashlib.md5(f"{rec['date']}|{rec['account_id']}|{rec['amount']:.2f}|{rec['name']}".encode()).hexdigest()
            out.append(rec)
        return out

    # --- sync -------------------------------------------------------------------
    def sync(self, conn: sqlite3.Connection, cfg: Config, as_of: str) -> SyncResult:
        result = SyncResult(self.name)
        if not self.configured():
            result.skipped = True
            result.detail["reason"] = "not configured"
            return result
        inst_filter = cfg.fina.institution_filter
        ticker_map = _ticker_map(conn)

        # balances → accounts
        bal_json = self._get("balance").json()
        store_raw(conn, self.name, "balance", None, bal_json)
        accounts = [b for b in self.parse_balances(bal_json) if not inst_filter or b["institute"] == inst_filter]
        id_map: dict[str, tuple[str, str]] = {}
        for b in accounts:
            kind = kind_from_name(b["name"] or "")
            aid = upsert_account(conn, source="fina", source_account_id=b["id"], name=b["name"] or b["id"],
                                 kind=kind, institution=b["institute"])
            if b.get("balance") is not None:
                record_balance(conn, aid, as_of, float(b["balance"]), b.get("available"), "fina")
            id_map[b["id"]] = (aid, kind)
        result.detail["accounts"] = len(accounts)

        # holdings → positions
        hold_json = self._get("holdings").json()
        store_raw(conn, self.name, "holdings", None, hold_json)
        n_pos = 0
        for acc in hold_json or []:
            info = acc.get("account") or {}
            if info.get("id") not in id_map:
                continue
            aid, _ = id_map[info["id"]]
            rows = []
            for h in acc.get("holdings") or []:
                name = h.get("name") or "Unknown"
                rows.append({"symbol": _symbol_for(name, ticker_map), "description": name,
                             "quantity": h.get("quantity"), "price": h.get("price"), "value": h.get("value") or 0,
                             "cost_basis": h.get("cost_basis"), "asset_class": asset_class_from_name(name)})
            n_pos += replace_positions(conn, aid, as_of, rows, "fina")
        result.detail["positions"] = n_pos

        # transactions
        txt = self._get("transactions").text
        cutoff = (date.today() - timedelta(days=cfg.fina.transaction_days)).isoformat()
        rules = compile_rules(cfg.flow_rules)
        added = skipped = 0
        for t in self.parse_transactions(txt):
            if t["date"] < cutoff or t["account_id"] not in id_map:
                skipped += 1
                continue
            aid, kind = id_map[t["account_id"]]
            if kind in cfg.fina.skip_kinds:
                skipped += 1
                continue
            legacy = find_legacy_id(conn, aid, t["date"], t["amount"], t["name"])
            _, status = upsert_transaction(conn, source="fina", source_txn_id=t["id"], account_id=aid,
                                           posted_at=t["date"], amount=t["amount"], description=t["name"],
                                           merchant=t["merchant"] or t["name"], category_raw=t["category"],
                                           currency=t["currency"], account_kind=kind, rules=rules,
                                           replaces_source_txn_id=legacy)
            added += status == "inserted"
            skipped += status == "skipped"
        result.detail.update({"transactions_added": added, "transactions_skipped": skipped})
        result.rows_written = len(accounts) + n_pos + added
        return result


def find_legacy_id(conn: sqlite3.Connection, account_id: str, posted_at: str, amount: float,
                   description: str | None) -> str | None:
    """Rows imported from the previous app carry synthetic ids (``fina_<date>_...``).
    When the live feed delivers the same transaction under Fina's own id, re-key
    the legacy row instead of inserting a duplicate."""
    row = conn.execute(
        "SELECT source_txn_id FROM transactions WHERE source = 'fina' AND source_txn_id LIKE 'fina_%'"
        " AND account_id = ? AND posted_at = ? AND ABS(amount - ?) < 0.005 AND COALESCE(description,'') = ?"
        " LIMIT 1", (account_id, posted_at, float(amount), description or "")).fetchone()
    return row["source_txn_id"] if row else None


def _ticker_map(conn) -> dict[str, str]:
    row = conn.execute("SELECT value FROM settings WHERE key = 'ticker_mappings'").fetchone()
    m = {k.lower(): v for k, v in (json.loads(row["value"]) if row else {}).items()}
    return {**KNOWN_SYMBOLS, **m}


def _symbol_for(name: str, ticker_map: dict[str, str]) -> str | None:
    n = (name or "").lower()
    if n in ticker_map:
        return ticker_map[n]
    for pat, sym in ticker_map.items():
        if pat and pat in n:
            return sym
    m = re.search(r"\(([A-Z]{2,5})\)", name or "")
    return m.group(1) if m else None
