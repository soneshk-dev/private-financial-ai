"""Category taxonomy and consistent recategorisation.

The taxonomy is ``Level 1 > Sub``. Level 1 is fixed (``MASTER_CATEGORIES``); sub-
categories are the provider mappings plus whatever the ledger already uses, so a
manual edit can only land on a known category unless the caller explicitly asks
to create a new one. Recategorising can cover one row or every row from the same
merchant, and can be remembered as a rule so future syncs classify the same way.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from ..db import now_iso
from ..ledger.classify import FINA_MAP, MASTER_CATEGORIES, PLAID_DETAILED, PLAID_LEVEL1, level1, normalize_category
from ..ledger.transactions import set_override

RULE_PRIORITY = 10          # user rules beat imported ones
KEEP_KEY = "category_taxonomy_extra"   # settings: JSON list of sub-categories the user promoted to the core taxonomy

# Curated sub-categories beyond what the provider mappings imply.
CURATED = {
    "Food & Dining": {"Food Delivery", "Bars & Nightlife"},
    "Shopping": {"Gifts", "Kids & Baby", "Home Goods", "Subscriptions & Boxes"},
    "Transportation": {"Car Payment", "Auto Insurance", "Tolls", "Auto Services"},
    "Entertainment": {"Subscriptions", "Music & Games", "Hobbies"},
    "Health & Wellness": {"Doctor & Dental", "Health Insurance", "Therapy & Counselling", "Vision"},
    "Home & Housing": {"Mortgage", "HOA & Assessments", "Property Tax", "Home Insurance", "Cleaning & Lawn", "Home"},
    "Utilities": {"Bills"},
    "Education": {"Tuition", "Childcare", "Books & Supplies", "Activities & Camps", "529 Contribution"},
    "Financial Services": {"Investment Trades", "Investment Sales", "Insurance", "Loans & Fees", "Taxes", "Fees",
                           "Advisory & Accounting", "Life Insurance"},
    "Business": {"Software & Subscriptions", "Professional Services", "Office & Equipment", "Payroll & Contractors",
                 "Marketing", "Travel & Meals", "Fees & Licences"},
    "Personal Care": {"Clothing Care", "Spa & Massage"},
    "Travel": {"Car Rental", "Trains & Transit", "Activities & Tours"},
    "Transfers": {"Internal Transfer", "Credit Card Payment", "Venmo & Zelle", "Crypto Transfer"},
    "Income": {"Business Income", "Rental Income", "Reimbursements", "Gifts Received", "Severance"},
    "Uncategorized": set(),
}


def default_subcategories() -> dict[str, set[str]]:
    """Sub-categories implied by the provider mappings, keyed by level 1."""
    subs: dict[str, set[str]] = {m: set() for m in MASTER_CATEGORIES}
    for key, sub in PLAID_DETAILED.items():
        if key == "OTHER":
            continue
        for prefix, l1 in PLAID_LEVEL1.items():
            if key.startswith(prefix + "_"):
                subs[l1].add(sub)
                break
    for v in FINA_MAP.values():
        if " > " in v:
            l1, sub = v.split(" > ", 1)
            subs.setdefault(l1, set()).add(sub)
    return subs


def kept(conn: sqlite3.Connection) -> set[str]:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (KEEP_KEY,)).fetchone()
    return set(json.loads(row["value"]) if row else [])


def set_kept(conn: sqlite3.Connection, category: str, keep: bool) -> set[str]:
    """Promote a sub-category into the core taxonomy (or demote it)."""
    cat = validate_category(conn, category)
    cur = kept(conn)
    (cur.add if keep else cur.discard)(cat)
    conn.execute("BEGIN")
    conn.execute("INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
                 " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                 (KEEP_KEY, json.dumps(sorted(cur)), now_iso()))
    conn.execute("COMMIT")
    return cur


def core_categories(conn: sqlite3.Connection) -> set[str]:
    """The categories the picker offers: provider defaults, the curated list and user-kept ones."""
    out = set(MASTER_CATEGORIES)
    for l1, subs in default_subcategories().items():
        out.update(f"{l1} > {s}" for s in subs)
    for l1, subs in CURATED.items():
        out.update(f"{l1} > {s}" for s in subs)
    out.update(kept(conn))
    return out


def _usage(conn: sqlite3.Connection) -> dict[str, tuple[int, str | None]]:
    return {r["category"]: (r["n"], r["last"]) for r in conn.execute(
        "SELECT category, COUNT(*) n, MAX(posted_at) last FROM transactions_v WHERE category IS NOT NULL GROUP BY category")}


def known_categories(conn: sqlite3.Connection) -> set[str]:
    out = set(MASTER_CATEGORIES)
    for l1, subs in default_subcategories().items():
        out.update(f"{l1} > {s}" for s in subs)
    out.update(_usage(conn))
    return out


def taxonomy(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Level-1 groups with their sub-categories and usage counts. ``core`` marks the
    curated taxonomy; the rest are in use (mostly inherited free-text names) and
    are candidates for merging."""
    used = _usage(conn)
    core = core_categories(conn)
    subs: dict[str, set[str]] = {m: set() for m in MASTER_CATEGORIES}
    for cat in core | set(used):
        l1, _, sub = cat.partition(" > ")
        if sub and l1 in subs:
            subs[l1].add(sub)
    out = []
    for l1 in MASTER_CATEGORIES:
        entries = []
        for s in sorted(subs[l1], key=lambda x: (f"{l1} > {x}" not in core, x.lower())):
            cat = f"{l1} > {s}"
            n, last = used.get(cat, (0, None))
            entries.append({"name": s, "category": cat, "n": n, "last": last, "core": cat in core})
        bare_n = used.get(l1, (0, None))[0]
        out.append({"level1": l1, "n": bare_n + sum(e["n"] for e in entries), "bare_n": bare_n,
                    "stray": sum(1 for e in entries if not e["core"]), "subs": entries})
    return out


_STOP = {"and", "or", "the", "of", "other", "general", "misc", "purchase", "purchases", "service", "services"}


def _stems(name: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", name.lower())
    out = set()
    for w in words:
        if w in _STOP or len(w) < 3:
            continue
        for suf in ("ies", "ing", "es", "s"):
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                w = w[: -len(suf)] + ("y" if suf == "ies" else "")
                break
        out.add(w)
    return out


def suggest_merges(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """For every in-use sub-category outside the core taxonomy, propose the core
    sub-category (same level 1) whose words it shares. Deterministic and cheap;
    the user accepts each one."""
    used = _usage(conn)
    core = core_categories(conn)
    by_l1: dict[str, list[tuple[str, set[str]]]] = {}
    for cat in core:
        l1, _, sub = cat.partition(" > ")
        if sub:
            by_l1.setdefault(l1, []).append((cat, _stems(sub)))
    out = []
    for cat, (n, last) in used.items():
        if cat in core or " > " not in cat:
            continue
        l1, _, sub = cat.partition(" > ")
        st = _stems(sub)
        best, score = None, 0.0
        for target, ts in by_l1.get(l1, []):
            if not ts:
                continue
            common = len(st & ts)
            if not common:
                continue
            sc = common / len(ts) + (0.5 if st == ts else 0) + (0.25 if next(iter(_stems(sub.split()[0]) or {""})) in ts else 0)
            if sc > score:
                best, score = target, sc
        if best and score >= 0.6:        # at least most of the target's words, or an exact/plural match
            out.append({"from": cat, "to": best, "n": n, "last": last, "confidence": round(min(score, 2) / 2, 2)})
    out.sort(key=lambda x: (-x["confidence"], -x["n"]))
    return out


def validate_category(conn: sqlite3.Connection, raw: str, allow_new: bool = False) -> str:
    """Normalise ``raw`` to canonical form and refuse unknown categories.

    Level 1 must be one of the master categories (case-insensitive). A new
    sub-category is only accepted with ``allow_new``."""
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("category is empty")
    l1_raw = raw.split(" > ", 1)[0].strip().lower()
    if l1_raw not in {m.lower() for m in MASTER_CATEGORIES}:
        raise ValueError(f"unknown level-1 category '{raw.split(' > ', 1)[0]}'; choose one of: " + ", ".join(MASTER_CATEGORIES))
    cat = normalize_category(raw, "text")
    if cat not in known_categories(conn) and not allow_new:
        raise ValueError(f"'{cat}' is not an existing category; pick one from the taxonomy or pass allow_new to create it")
    return cat


def merchant_key(row: sqlite3.Row | dict[str, Any]) -> str:
    return ((row["merchant"] or row["description"] or "")).strip()


def similar(conn: sqlite3.Connection, txn_id: str) -> dict[str, Any]:
    """Other transactions from the same merchant and how they are categorised today."""
    row = conn.execute("SELECT * FROM transactions_v WHERE id = ?", (txn_id,)).fetchone()
    if row is None:
        raise KeyError(txn_id)
    key = merchant_key(row)
    rows = conn.execute(
        "SELECT category, COUNT(*) n, SUM(amount) total FROM transactions_v"
        " WHERE LOWER(TRIM(COALESCE(merchant, description, ''))) = LOWER(?) AND id != ? GROUP BY category ORDER BY n DESC",
        (key, txn_id)).fetchall()
    rule = conn.execute("SELECT id, category FROM category_rules WHERE match_kind = 'exact' AND LOWER(pattern) = LOWER(?)"
                        " ORDER BY priority DESC LIMIT 1", (key,)).fetchone()
    return {"merchant": key, "n": sum(r["n"] for r in rows),
            "categories": [{"category": r["category"], "n": r["n"], "total": round(r["total"] or 0, 2)} for r in rows],
            "rule": dict(rule) if rule else None}


def recategorize(conn: sqlite3.Connection, txn_id: str, category: str, *, scope: str = "one",
                 remember: bool = False, allow_new: bool = False) -> dict[str, Any]:
    """Set a category override on one transaction or on every row from its merchant.

    ``remember`` stores an exact-match merchant rule so newly synced rows get the
    same category. Returns the canonical category and how many rows changed."""
    if scope not in ("one", "merchant"):
        raise ValueError("scope must be 'one' or 'merchant'")
    row = conn.execute("SELECT * FROM transactions_v WHERE id = ?", (txn_id,)).fetchone()
    if row is None:
        raise KeyError(txn_id)
    cat = validate_category(conn, category, allow_new)
    key = merchant_key(row)
    if scope == "merchant" and key:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM transactions_v WHERE LOWER(TRIM(COALESCE(merchant, description, ''))) = LOWER(?)", (key,))]
    else:
        ids = [txn_id]
    conn.execute("BEGIN")
    for tid in ids:
        set_override(conn, tid, category=cat)
    rule_id = None
    if remember and key:
        conn.execute("DELETE FROM category_rules WHERE match_kind = 'exact' AND LOWER(pattern) = LOWER(?) AND source = 'user'", (key,))
        cur = conn.execute("INSERT INTO category_rules (pattern, match_kind, category, flow_type, priority, source, created_at)"
                           " VALUES (?, 'exact', ?, NULL, ?, 'user', ?)", (key, cat, RULE_PRIORITY, now_iso()))
        rule_id = cur.lastrowid
    conn.execute("COMMIT")
    return {"id": txn_id, "category": cat, "scope": scope, "merchant": key, "affected": len(ids), "rule_id": rule_id}


def rename_category(conn: sqlite3.Connection, old: str, new: str, *, allow_new: bool = False) -> dict[str, Any]:
    """Move every transaction whose effective category is ``old`` to ``new`` (merge
    if ``new`` exists) and repoint rules and budgets."""
    new_cat = validate_category(conn, new, allow_new)
    old = old.strip()
    if old == new_cat:
        return {"from": old, "to": new_cat, "affected": 0, "rules": 0}
    conn.execute("BEGIN")
    cur = conn.execute("UPDATE transactions SET category_override = ?, updated_at = ? WHERE id IN"
                       " (SELECT id FROM transactions_v WHERE category = ?)", (new_cat, now_iso(), old))
    n = cur.rowcount
    rules = conn.execute("UPDATE category_rules SET category = ? WHERE category = ?", (new_cat, old)).rowcount
    old_l1, _, old_sub = old.partition(" > ")
    new_l1, _, new_sub = new_cat.partition(" > ")
    if old_sub and new_sub:
        conn.execute("UPDATE budgets SET category_l1 = ? WHERE category_l1 = ?", (new_sub, old_sub))
    conn.execute("COMMIT")
    return {"from": old, "to": new_cat, "affected": n, "rules": rules}


def list_rules(conn: sqlite3.Connection, user_only: bool = False) -> list[dict[str, Any]]:
    where = " WHERE source = 'user'" if user_only else ""
    return [dict(r) for r in conn.execute(
        "SELECT id, pattern, match_kind, category, flow_type, priority, source, created_at FROM category_rules"
        + where + " ORDER BY source = 'user' DESC, priority DESC, pattern")]


def rule_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {r["source"] or "": r["n"] for r in conn.execute(
        "SELECT source, COUNT(*) n FROM category_rules GROUP BY source")}


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> bool:
    conn.execute("BEGIN")
    n = conn.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,)).rowcount
    conn.execute("COMMIT")
    return n > 0
