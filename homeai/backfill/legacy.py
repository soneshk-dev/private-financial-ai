"""One-time import from the previous Shah AI database (``vault/databases/main.db``).

Maps the old tables onto the ledger. Provider ids are preserved so the
connectors continue where the old app left off (Plaid cursors included).
Safe to re-run: every write is an upsert keyed by provider id.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any

from ..config import Config
from ..db import now_iso
from ..ledger.accounts import kind_from_name, kind_from_plaid, upsert_account
from ..ledger.balances import record_balance, replace_defi, replace_positions
from ..ledger.classify import compile_rules, normalize_category
from ..ledger.transactions import upsert_transaction


def _kind_from_csv_type(t: str | None, nickname: str | None) -> str:
    s = f"{t or ''} {nickname or ''}".lower()
    if "credit" in s or "card" in s or "visa" in s:
        return "credit_card"
    if "saving" in s:
        return "savings"
    if "check" in s or "cash" in s:
        return "checking"
    if "401" in s or "brokerage" in s or "ira" in s or "hsa" in s:
        return kind_from_name(s)
    return "checking"


def backfill(conn: sqlite3.Connection, cfg: Config, old_db: str, as_of: str | None = None) -> dict[str, Any]:
    as_of = as_of or date.today().isoformat()
    old = sqlite3.connect(f"file:{old_db}?mode=ro", uri=True)
    old.row_factory = sqlite3.Row
    counts: dict[str, int] = {}
    rules = compile_rules(cfg.flow_rules)
    conn.execute("BEGIN")
    try:
        old_to_new: dict[str, str] = {}           # old local account id → new account id
        kinds: dict[str, str] = {}

        # --- Plaid connections + accounts ------------------------------------
        for r in old.execute("SELECT * FROM plaid_items"):
            status = {"active": "active", "removed": "removed", "revoked": "removed"}.get(r["status"] or "active", "active")
            if r["error_code"] == "ITEM_LOGIN_REQUIRED":
                status = "login_required"
            ts = now_iso()
            conn.execute(
                "INSERT INTO connections (id, connector, institution, status, secret_enc, cursor, error_code,"
                " error_message, last_success_at, meta, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET secret_enc=excluded.secret_enc, cursor=excluded.cursor,"
                " status=excluded.status, updated_at=excluded.updated_at",
                (r["item_id"], "plaid", r["institution_name"], status, r["access_token"], r["transactions_cursor"],
                 r["error_code"], r["error_message"], r["last_sync_at"],
                 json.dumps({"institution_id": r["institution_id"], "products": ["transactions"]}),
                 r["created_at"] or ts, ts))
            counts["connections"] = counts.get("connections", 0) + 1
        item_status = {r["item_id"]: r["status"] for r in old.execute("SELECT item_id, status FROM plaid_items")}
        for r in old.execute("SELECT pa.*, pi.institution_name FROM plaid_accounts pa JOIN plaid_items pi USING(item_id)"):
            kind = kind_from_plaid(r["account_type"], r["account_subtype"], r["account_name"], r["institution_name"], cfg)
            active = bool(r["is_active"]) and item_status.get(r["item_id"]) == "active"
            aid = upsert_account(conn, source="plaid", source_account_id=r["plaid_account_id"], name=r["account_name"],
                                 kind=kind, institution=r["institution_name"], mask=r["mask"],
                                 connection_id=r["item_id"], is_active=active,
                                 meta={"official_name": r["official_name"], "plaid_type": r["account_type"],
                                       "plaid_subtype": r["account_subtype"], "legacy_local_id": r["local_account_id"]})
            if r["local_account_id"]:
                old_to_new[r["local_account_id"]] = aid
            kinds[aid] = kind
            if active and r["current_balance"] is not None:
                record_balance(conn, aid, as_of, float(r["current_balance"]), r["available_balance"], "plaid")
            counts["plaid_accounts"] = counts.get("plaid_accounts", 0) + 1

        # --- Fidelity (Fina) accounts + holdings ---------------------------------
        for r in old.execute("SELECT * FROM investment_accounts"):
            if r["fina_account_id"]:
                kind = kind_from_name(r["account_name"], r["account_type"] or "brokerage")
                if (r["account_type"] or "") == "credit_card":
                    kind = "credit_card"
                aid = upsert_account(conn, source="fina", source_account_id=r["fina_account_id"], name=r["account_name"],
                                     kind=kind, institution=r["institution"] or "Fidelity", is_active=bool(r["is_active"]),
                                     meta={"legacy_account_id": r["account_id"], "legacy_type": r["account_type"]})
                if r["is_active"] and r["fina_balance"] is not None:
                    bal_date = (r["last_synced"] or as_of)[:10]
                    record_balance(conn, aid, bal_date, float(r["fina_balance"]), None, "fina")
            else:
                aid = upsert_account(conn, source="csv", source_account_id=f"inv:{r['account_id']}",
                                     name=r["account_name"], kind=kind_from_name(r["account_name"], r["account_type"] or "brokerage"),
                                     institution=r["institution"], is_active=False,
                                     meta={"legacy_account_id": r["account_id"]})
            old_to_new[r["account_id"]] = aid
            kinds[aid] = conn.execute("SELECT kind FROM accounts WHERE id=?", (aid,)).fetchone()[0]
            counts["investment_accounts"] = counts.get("investment_accounts", 0) + 1

        by_acct: dict[str, list[dict]] = {}
        for h in old.execute("SELECT h.*, ia.is_active FROM holdings h JOIN investment_accounts ia USING(account_id)"):
            if not h["is_active"]:
                continue
            aid = old_to_new.get(h["account_id"])
            if not aid:
                continue
            cls = {"Cash": "cash", "ETF": "etf", "Mutual Fund": "fund", "Stock": "equity", "Crypto": "crypto",
                   "Investment": "equity"}.get(h["asset_type"] or "", "other")
            by_acct.setdefault(aid, []).append({"symbol": h["symbol"], "description": h["description"],
                                                "quantity": h["quantity"], "price": h["current_price"],
                                                "value": h["current_value"], "cost_basis": h["cost_basis_total"],
                                                "asset_class": cls})
        for aid, rows in by_acct.items():
            counts["positions"] = counts.get("positions", 0) + replace_positions(conn, aid, as_of, rows, "fina")

        # --- crypto wallets (Zerion) --------------------------------------------
        for w in old.execute("SELECT * FROM crypto_wallets"):
            aid = upsert_account(conn, source="zerion", source_account_id=f"{w['chain']}:{w['address']}",
                                 name=w["wallet_name"], kind="crypto_wallet", institution=(w["chain"] or "ethereum").title(),
                                 is_active=bool(w["is_active"]), meta={"chain": w["chain"], "address": w["address"]})
            old_to_new[w["wallet_id"]] = aid
            toks = [{"symbol": b["token_symbol"], "description": b["token_symbol"], "quantity": b["balance"],
                     "value": b["balance_usd"] or 0, "asset_class": "nft" if b["token_symbol"] == "NFTs" else "crypto"}
                    for b in old.execute("SELECT * FROM crypto_balances WHERE wallet_id=?", (w["wallet_id"],))]
            seen: dict[str, dict] = {}
            for t in toks:
                if t["symbol"] in seen:
                    seen[t["symbol"]]["value"] += t["value"]
                else:
                    seen[t["symbol"]] = t
            counts["positions"] = counts.get("positions", 0) + replace_positions(conn, aid, as_of, seen.values(), "zerion")
            defi = [{"protocol": d["protocol"], "protocol_slug": d["protocol_slug"], "network": d["network"],
                     "meta_type": "SUPPLIED" if d["meta_type"] == "APP_TOKEN" else d["meta_type"],
                     "symbol": d["token_symbol"], "quantity": d["token_balance"], "price": d["token_price"],
                     "value": d["balance_usd"], "contract": d["contract_address"]}
                    for d in old.execute("SELECT * FROM defi_position_details WHERE wallet_id=?", (w["wallet_id"],))]
            counts["defi"] = counts.get("defi", 0) + replace_defi(conn, aid, as_of, defi)
            tok_total = sum(t["value"] for t in seen.values())
            defi_total = old.execute("SELECT COALESCE(SUM(balance_usd),0) FROM defi_positions WHERE wallet_id=?",
                                     (w["wallet_id"],)).fetchone()[0]
            record_balance(conn, aid, as_of, tok_total + defi_total, None, "zerion")

        # --- bitcoin wallets ----------------------------------------------------
        for w in old.execute("SELECT * FROM bitcoin_wallets"):
            aid = upsert_account(conn, source="bitcoin", source_account_id=w["wallet_name"], name=w["wallet_name"],
                                 kind="crypto_wallet", institution="Bitcoin")
            btc, usd = float(w["total_balance_btc"] or 0), float(w["total_balance_usd"] or 0)
            replace_positions(conn, aid, as_of, [{"symbol": "BTC", "description": "Bitcoin", "quantity": btc,
                                                  "price": (usd / btc) if btc else None, "value": usd,
                                                  "asset_class": "crypto"}], "bitcoin")
            record_balance(conn, aid, as_of, usd, None, "bitcoin")
            counts["bitcoin_wallets"] = counts.get("bitcoin_wallets", 0) + 1
        if counts.get("bitcoin_wallets"):
            conn.execute("INSERT INTO connector_health (connector, status, last_success_at, rows_written) VALUES"
                         " ('bitcoin','ok',?,0) ON CONFLICT(connector) DO NOTHING", (now_iso(),))

        # --- legacy CSV accounts referenced by transactions ------------------------
        csv_accts = {r["account_id"]: r for r in old.execute("SELECT * FROM accounts")}

        # --- transactions --------------------------------------------------------
        overrides = {r["txn_id"]: r["new_category"] for r in old.execute("SELECT txn_id, new_category FROM category_overrides")}
        unknown_aid = None
        n_ins = n_skip = 0
        for t in old.execute("SELECT * FROM transactions WHERE is_duplicate = 0"):
            src = t["source_type"] or "csv"
            if src == "plaid":
                sid = t["plaid_transaction_id"] or t["txn_id"]
            else:
                sid = t["txn_id"]
            aid = old_to_new.get(t["account_id"] or "")
            if not aid and t["account_id"] in csv_accts:
                c = csv_accts[t["account_id"]]
                aid = upsert_account(conn, source="csv", source_account_id=c["account_id"],
                                     name=c["nickname"] or f"{c['institution'] or ''} {c['account_type'] or ''}".strip() or c["account_id"],
                                     kind=_kind_from_csv_type(c["account_type"], c["nickname"]), institution=c["institution"],
                                     is_active=False, meta={"legacy_account_id": c["account_id"]})
                old_to_new[t["account_id"]] = aid
            if not aid:
                if unknown_aid is None:
                    unknown_aid = upsert_account(conn, source="csv", source_account_id="legacy-unknown",
                                                 name="Unknown (legacy import)", kind="other", is_active=False)
                aid = unknown_aid
            kind = kinds.get(aid) or conn.execute("SELECT kind FROM accounts WHERE id=?", (aid,)).fetchone()[0]
            kinds[aid] = kind
            cat = t["category_normalized"] or normalize_category(t["category_raw"], src if src in ("plaid", "fina") else None)
            flow = "transfer" if t["is_transfer"] else None
            _, status = upsert_transaction(
                conn, source=src, source_txn_id=sid, account_id=aid, posted_at=t["txn_date"][:10],
                amount=float(t["amount"] or 0), description=t["description"], merchant=t["merchant"],
                category_raw=t["category_raw"] or (t["personal_finance_category_detailed"] if src == "plaid" else None),
                category=cat, currency=t["currency"] or "USD", pending=bool(t["pending"]), account_kind=kind,
                flow_type=flow, rules=rules, meta={"legacy_txn_id": t["txn_id"], "legacy_source_file": t["source_file_id"]})
            if t["txn_id"] in overrides:
                conn.execute("UPDATE transactions SET category_override = ? WHERE source = ? AND source_txn_id = ?",
                             (overrides[t["txn_id"]], src, sid))
            n_ins += status == "inserted"
            n_skip += status != "inserted"
        counts["transactions"] = n_ins
        counts["transactions_existing"] = n_skip

        # --- budgets, category rules, ticker mappings ----------------------------
        for b in old.execute("SELECT * FROM budgets"):
            conn.execute("INSERT INTO budgets (category_l1, monthly_limit, effective_from, effective_until,"
                         " alert_threshold, is_active) VALUES (?,?,?,?,?,?)",
                         (b["category_level1"] or b["category_normalized"], float(b["monthly_limit"]), b["effective_from"],
                          b["effective_until"], float(b["alert_threshold"] or 0.8), int(bool(b["is_active"]))))
            counts["budgets"] = counts.get("budgets", 0) + 1
        existing_rules = conn.execute("SELECT COUNT(*) FROM category_rules").fetchone()[0]
        if existing_rules == 0:
            for r in old.execute("SELECT * FROM category_rules WHERE merchant_pattern IS NOT NULL AND category_full IS NOT NULL"):
                conn.execute("INSERT INTO category_rules (pattern, match_kind, category, priority, source, created_at)"
                             " VALUES (?,?,?,?,?,?)",
                             (r["merchant_pattern"], "exact" if (r["rule_type"] or "") == "exact" else "contains",
                              normalize_category(r["category_full"], None), int(r["usage_count"] or 0),
                              f"legacy:{r['rule_type'] or 'rule'}", now_iso()))
                counts["category_rules"] = counts.get("category_rules", 0) + 1
        tickers = {r["description_pattern"]: r["ticker"] for r in old.execute("SELECT * FROM ticker_mappings")}
        for h in old.execute("SELECT DISTINCT description, symbol FROM holdings WHERE symbol IS NOT NULL"):
            tickers.setdefault(h["description"], h["symbol"])
        conn.execute("INSERT INTO settings (key, value, updated_at) VALUES ('ticker_mappings', ?, ?)"
                     " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                     (json.dumps(tickers), now_iso()))
        counts["ticker_mappings"] = len(tickers)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        old.close()
    return counts
