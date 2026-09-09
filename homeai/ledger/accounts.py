"""Accounts: stable ids, upserts that respect user overrides, lookups."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from ..config import Config, KIND_CLASS, LIABILITY_KINDS
from ..db import now_iso


def account_id(source: str, source_account_id: str) -> str:
    return "acc_" + hashlib.sha1(f"{source}:{source_account_id}".encode()).hexdigest()[:16]


def upsert_account(conn: sqlite3.Connection, *, source: str, source_account_id: str, name: str,
                   kind: str, institution: str | None = None, mask: str | None = None,
                   connection_id: str | None = None, entity: str | None = None,
                   currency: str = "USD", is_active: bool | None = None,
                   meta: dict[str, Any] | None = None) -> str:
    """Create or update an account. Locked fields (kind/entity/name/is_active set by
    an override or by hand) are preserved on update."""
    aid = account_id(source, source_account_id)
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    ts = now_iso()
    if row is None:
        conn.execute(
            "INSERT INTO accounts (id, source, source_account_id, name, institution, kind, is_liability, entity,"
            " currency, mask, is_active, connection_id, meta, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (aid, source, source_account_id, name, institution, kind, int(kind in LIABILITY_KINDS),
             entity or "personal", currency, mask, int(True if is_active is None else is_active),
             connection_id, json.dumps(meta or {}), ts, ts))
        return aid
    locked = set(json.loads(row["meta"] or "{}").get("locked", []))
    old_meta = json.loads(row["meta"] or "{}")
    new_meta = {**old_meta, **(meta or {})}
    new_meta["locked"] = sorted(locked)
    updates = {
        "institution": institution if institution is not None else row["institution"],
        "mask": mask if mask is not None else row["mask"],
        "connection_id": connection_id if connection_id is not None else row["connection_id"],
        "currency": currency or row["currency"],
        "meta": json.dumps(new_meta),
        "updated_at": ts,
    }
    if "name" not in locked and name:
        updates["name"] = name
    if "kind" not in locked and kind:
        updates["kind"] = kind
        updates["is_liability"] = int(kind in LIABILITY_KINDS)
    if "entity" not in locked and entity:
        updates["entity"] = entity
    if "is_active" not in locked and is_active is not None:
        updates["is_active"] = int(is_active)
    sets = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(f"UPDATE accounts SET {sets} WHERE id = ?", (*updates.values(), aid))
    return aid


def set_locked(conn: sqlite3.Connection, aid: str, **fields: Any) -> None:
    """Set fields by hand and lock them against connector updates."""
    row = conn.execute("SELECT meta FROM accounts WHERE id = ?", (aid,)).fetchone()
    if row is None:
        raise KeyError(aid)
    meta = json.loads(row["meta"] or "{}")
    locked = set(meta.get("locked", []))
    updates: dict[str, Any] = {}
    for k, v in fields.items():
        if k not in ("kind", "entity", "name", "is_active"):
            raise ValueError(f"cannot lock {k}")
        updates[k] = int(v) if k == "is_active" else v
        locked.add(k)
        if k == "kind":
            updates["is_liability"] = int(v in LIABILITY_KINDS)
    meta["locked"] = sorted(locked)
    updates["meta"] = json.dumps(meta)
    updates["updated_at"] = now_iso()
    sets = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(f"UPDATE accounts SET {sets} WHERE id = ?", (*updates.values(), aid))


def apply_overrides(conn: sqlite3.Connection, cfg: Config) -> int:
    """Apply config.account_overrides (match → set) as locked fields."""
    n = 0
    rows = conn.execute("SELECT * FROM accounts").fetchall()
    for ov in cfg.account_overrides:
        for r in rows:
            if _matches(r, ov.match, cfg):
                set_locked(conn, r["id"], **ov.set)
                n += 1
    return n


def _matches(row: sqlite3.Row, match: dict[str, Any], cfg: Config) -> bool:
    for k, v in match.items():
        if k == "name_contains":
            if v.lower() not in (row["name"] or "").lower():
                return False
        elif k == "institution":
            if (row["institution"] or "").lower() != str(v).lower():
                return False
        elif k in ("source", "source_account_id", "mask", "kind", "connection_id"):
            if str(row[k]) != str(v):
                return False
        else:
            return False
    return True


def ensure_manual_accounts(conn: sqlite3.Connection, cfg: Config) -> list[str]:
    """Manual accounts from config: upsert + record today's balance."""
    from .balances import record_balance
    from datetime import date
    ids = []
    for m in cfg.manual_accounts:
        aid = upsert_account(conn, source="manual", source_account_id=m.name, name=m.name, kind=m.kind,
                             institution=m.institution or None, entity=m.entity)
        record_balance(conn, aid, date.today().isoformat(), m.balance, source="manual")
        ids.append(aid)
    return ids


def list_accounts(conn: sqlite3.Connection, active_only: bool = True) -> list[dict[str, Any]]:
    sql = ("SELECT a.*, b.balance AS latest_balance, b.as_of AS balance_as_of FROM accounts a "
           "LEFT JOIN (SELECT account_id, balance, as_of FROM balances_daily bd "
           "           WHERE as_of = (SELECT MAX(as_of) FROM balances_daily WHERE account_id = bd.account_id)) b"
           " ON b.account_id = a.id")
    if active_only:
        sql += " WHERE a.is_active = 1"
    sql += " ORDER BY a.is_liability, a.kind, a.institution, a.name"
    out = []
    for r in conn.execute(sql):
        d = dict(r)
        d["meta"] = json.loads(d.get("meta") or "{}")
        d["asset_class"] = KIND_CLASS.get(d["kind"], "other")
        out.append(d)
    return out


def get_account(conn: sqlite3.Connection, aid: str) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    return dict(r) if r else None


def find_by_source(conn: sqlite3.Connection, source: str, source_account_id: str) -> str | None:
    r = conn.execute("SELECT id FROM accounts WHERE source = ? AND source_account_id = ?",
                     (source, source_account_id)).fetchone()
    return r["id"] if r else None


# --- kind detection helpers shared by connectors and the backfill ---------------
def kind_from_name(name: str, fallback: str = "brokerage") -> str:
    n = (name or "").lower()
    if "roth" in n and ("401" in n or "brokeragelink" in n):
        return "roth_401k"
    if "roth" in n:
        return "roth_ira"
    if "401" in n or "savings incentive" in n or "brokeragelink" in n:
        return "retirement_401k"
    if "deferred comp" in n or "serp" in n or "supplemental executive" in n or "supplemental defined" in n \
            or "deferred compensation" in n:
        return "deferred_comp"
    if "rollover ira" in n or " ira" in n or n.startswith("ira"):
        return "ira"
    if "hsa" in n or "health savings" in n:
        return "hsa"
    if "529" in n or "college" in n:
        return "e529"
    if "cash management" in n:
        return "cash_mgmt"
    if "youth" in n or "custodial" in n or "utma" in n or "ugma" in n:
        return "custodial"
    if "visa" in n or "credit card" in n or "mastercard" in n or "card" in n:
        return "credit_card"
    return fallback


def kind_from_plaid(acct_type: str | None, subtype: str | None, name: str | None,
                    institution: str | None, cfg: Config | None = None) -> str:
    t = (acct_type or "").lower()
    s = (subtype or "").lower()
    n = (name or "").lower()
    inst = (institution or "").lower()
    if t == "depository":
        return {"checking": "checking", "savings": "savings", "money market": "money_market",
                "cd": "cd", "hsa": "hsa", "cash management": "cash_mgmt"}.get(s, "checking")
    if t == "credit":
        return "credit_card"
    if t == "loan":
        helocs = [h.lower() for h in (cfg.heloc_institutions if cfg else [])]
        if s in ("home equity", "line of credit") or "heloc" in n or "equity" in n or any(h in inst for h in helocs):
            return "heloc"
        if s == "mortgage" or "mortgage" in n:
            return "mortgage"
        if s == "student":
            return "student_loan"
        return "loan"
    if t == "investment" or t == "brokerage":
        if s in ("crypto exchange", "crypto"):
            return "crypto_exchange"
        return {"401k": "retirement_401k", "roth 401k": "roth_401k", "ira": "ira", "roth": "roth_ira",
                "hsa": "hsa", "529": "e529", "brokerage": "brokerage"}.get(s, kind_from_name(name or "", "brokerage"))
    return "other"
