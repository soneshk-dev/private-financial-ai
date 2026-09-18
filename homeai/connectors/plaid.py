"""Plaid: banks, cards, mortgages, and brokerages (holdings + investment transactions where consented).

Access tokens are Fernet-encrypted at rest with a key file in the secrets dir.
Transactions use ``/transactions/sync`` with a per-connection cursor; a posted
transaction that carries ``pending_transaction_id`` re-keys the pending row
instead of creating a second one.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any

from ..config import Config
from ..db import now_iso
from ..ledger.accounts import kind_from_plaid, upsert_account
from ..ledger.balances import record_balance, replace_positions
from ..ledger.classify import compile_rules
from ..ledger.transactions import remove_transaction, upsert_transaction
from .base import SyncResult, parse_kv_conf, store_raw


class PlaidConnector:
    name = "plaid"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        conf = parse_kv_conf(cfg.secrets_dir / cfg.plaid.conf_file)
        self.client_id = conf.get("PLAID_CLIENT_ID")
        self.secret = conf.get("PLAID_SECRET")
        self.env = conf.get("PLAID_ENV", "sandbox")
        self._client = None
        self._fernet = None
        self._key_path = cfg.secrets_dir / cfg.plaid.key_file

    # --- infra -------------------------------------------------------------
    def configured(self) -> bool:
        return bool(self.client_id and self.secret)

    def _fernet_obj(self):
        from cryptography.fernet import Fernet
        if self._fernet is None:
            if self._key_path.exists():
                key = self._key_path.read_bytes().strip()
            else:
                key = Fernet.generate_key()
                self._key_path.parent.mkdir(parents=True, exist_ok=True)
                self._key_path.write_bytes(key)
                self._key_path.chmod(0o600)
            self._fernet = Fernet(key)
        return self._fernet

    def encrypt(self, token: str) -> str:
        return self._fernet_obj().encrypt(token.encode()).decode()

    def decrypt(self, enc: str) -> str:
        return self._fernet_obj().decrypt(enc.encode()).decode()

    def client(self):
        if self._client is None:
            import plaid
            from plaid.api import plaid_api
            host = {"sandbox": plaid.Environment.Sandbox, "production": plaid.Environment.Production}.get(
                self.env, plaid.Environment.Sandbox)
            configuration = plaid.Configuration(host=host, api_key={"clientId": self.client_id, "secret": self.secret})
            self._client = plaid_api.PlaidApi(plaid.ApiClient(configuration))
        return self._client

    # --- link flow ---------------------------------------------------------
    def create_link_token(self, user_id: str = "default", access_token: str | None = None,
                          redirect_uri: str | None = None) -> dict[str, Any]:
        from plaid.model.country_code import CountryCode
        from plaid.model.link_token_create_request import LinkTokenCreateRequest
        from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
        from plaid.model.products import Products
        kwargs: dict[str, Any] = dict(
            user=LinkTokenCreateRequestUser(client_user_id=user_id),
            client_name=self.cfg.plaid.client_name,
            country_codes=[CountryCode(c) for c in self.cfg.plaid.country_codes],
            language="en",
        )
        extra = [Products(p) for p in self.cfg.plaid.extra_products]
        if access_token:
            kwargs["access_token"] = access_token          # update mode (re-auth / add consent)
            if extra:
                kwargs["additional_consented_products"] = extra
        else:
            kwargs["products"] = [Products(p) for p in self.cfg.plaid.products]
            if extra:
                kwargs["required_if_supported_products"] = extra
        if redirect_uri:
            kwargs["redirect_uri"] = redirect_uri
        resp = self.client().link_token_create(LinkTokenCreateRequest(**kwargs))
        return {"link_token": resp.link_token, "expiration": str(resp.expiration)}

    def link_token_for_update(self, conn: sqlite3.Connection, connection_id: str, redirect_uri: str | None = None):
        row = conn.execute("SELECT secret_enc FROM connections WHERE id = ?", (connection_id,)).fetchone()
        if not row:
            raise KeyError(connection_id)
        return self.create_link_token(access_token=self.decrypt(row["secret_enc"]), redirect_uri=redirect_uri)

    def exchange_public_token(self, conn: sqlite3.Connection, public_token: str) -> dict[str, Any]:
        from plaid.model.country_code import CountryCode
        from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest
        from plaid.model.item_get_request import ItemGetRequest
        from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
        c = self.client()
        ex = c.item_public_token_exchange(ItemPublicTokenExchangeRequest(public_token=public_token))
        item = c.item_get(ItemGetRequest(access_token=ex.access_token)).item
        inst_name = None
        if item.institution_id:
            inst = c.institutions_get_by_id(InstitutionsGetByIdRequest(
                institution_id=item.institution_id, country_codes=[CountryCode("US")]))
            inst_name = inst.institution.name
        products = sorted({str(p) for p in (getattr(item, "consented_products", None) or [])}
                          | {str(p) for p in (getattr(item, "billed_products", None) or [])})
        ts = now_iso()
        conn.execute(
            "INSERT INTO connections (id, connector, institution, status, secret_enc, meta, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET secret_enc=excluded.secret_enc, status='active',"
            " institution=excluded.institution, error_code=NULL, error_message=NULL, meta=excluded.meta, updated_at=excluded.updated_at",
            (ex.item_id, "plaid", inst_name, "active", self.encrypt(ex.access_token),
             json.dumps({"institution_id": item.institution_id, "products": products}), ts, ts))
        n = self._sync_accounts(conn, ex.item_id, ex.access_token, inst_name, date.today().isoformat())
        return {"connection_id": ex.item_id, "institution": inst_name, "accounts": n, "products": products}

    def refresh_products(self, conn: sqlite3.Connection, connection_id: str, token: str | None = None) -> list[str]:
        """Re-read what the item is consented for (it changes after Link update mode) into connections.meta."""
        from plaid.model.item_get_request import ItemGetRequest
        row = conn.execute("SELECT secret_enc, meta FROM connections WHERE id = ?", (connection_id,)).fetchone()
        if not row:
            raise KeyError(connection_id)
        item = self.client().item_get(ItemGetRequest(access_token=token or self.decrypt(row["secret_enc"]))).item
        products = sorted({str(p) for p in (getattr(item, "consented_products", None) or [])}
                          | {str(p) for p in (getattr(item, "billed_products", None) or [])}
                          | {str(p) for p in (getattr(item, "products", None) or [])})
        meta = json.loads(row["meta"] or "{}")
        meta["products"] = products
        meta["available_products"] = sorted(str(p) for p in (getattr(item, "available_products", None) or []))
        conn.execute("UPDATE connections SET meta = ?, updated_at = ? WHERE id = ?", (json.dumps(meta), now_iso(), connection_id))
        return products

    def remove_connection(self, conn: sqlite3.Connection, connection_id: str) -> None:
        from plaid.model.item_remove_request import ItemRemoveRequest
        row = conn.execute("SELECT secret_enc FROM connections WHERE id = ?", (connection_id,)).fetchone()
        if row and row["secret_enc"]:
            try:
                self.client().item_remove(ItemRemoveRequest(access_token=self.decrypt(row["secret_enc"])))
            except Exception:  # noqa: BLE001
                pass
        conn.execute("UPDATE connections SET status = 'removed', updated_at = ? WHERE id = ?", (now_iso(), connection_id))
        conn.execute("UPDATE accounts SET is_active = 0, updated_at = ? WHERE connection_id = ?", (now_iso(), connection_id))

    # --- sync --------------------------------------------------------------
    def sync(self, conn: sqlite3.Connection, cfg: Config, as_of: str) -> SyncResult:
        result = SyncResult(self.name)
        if not self.configured():
            result.skipped = True
            result.detail["reason"] = "not configured"
            return result
        rows = conn.execute("SELECT * FROM connections WHERE connector = 'plaid' AND status != 'removed'").fetchall()
        if not rows:
            result.skipped = True
            result.detail["reason"] = "no connections"
            return result
        details = []
        any_error = False
        for r in rows:
            d: dict[str, Any] = {"connection_id": r["id"], "institution": r["institution"]}
            try:
                token = self.decrypt(r["secret_enc"])
                d["accounts"] = self._sync_accounts(conn, r["id"], token, r["institution"], as_of)
                d.update(self._sync_transactions(conn, r["id"], token, r["cursor"]))
                products = self.refresh_products(conn, r["id"], token)
                if "investments" in products:
                    d["holdings"] = self._sync_holdings(conn, r["id"], token, as_of)
                    d.update(self._sync_investment_transactions(conn, r["id"], token))
                conn.execute("UPDATE connections SET status='active', error_code=NULL, error_message=NULL,"
                             " last_success_at=?, updated_at=? WHERE id=?", (now_iso(), now_iso(), r["id"]))
                result.rows_written += d.get("added", 0) + d.get("modified", 0) + d.get("accounts", 0)
            except Exception as e:  # noqa: BLE001
                code, msg = _plaid_error(e)
                d["error"] = f"{code}: {msg}"[:500]
                status = "login_required" if code in ("ITEM_LOGIN_REQUIRED", "PENDING_EXPIRATION",
                                                       "ITEM_NOT_SUPPORTED") else "error"
                conn.execute("UPDATE connections SET status=?, error_code=?, error_message=?, updated_at=? WHERE id=?",
                             (status, code, msg[:500], now_iso(), r["id"]))
                any_error = True
            details.append(d)
        result.detail["connections"] = details
        # A single bad institution should not mark the whole connector failed if others worked.
        result.ok = not any_error or any("error" not in d for d in details)
        if any_error:
            result.error = "; ".join(f"{d['institution']}: {d['error']}" for d in details if "error" in d)
        return result

    def _sync_accounts(self, conn, connection_id: str, token: str, institution: str | None, as_of: str) -> int:
        from plaid.model.accounts_get_request import AccountsGetRequest
        resp = self.client().accounts_get(AccountsGetRequest(access_token=token))
        store_raw(conn, self.name, "accounts_get", connection_id, resp.to_dict())
        n = 0
        for a in resp.accounts:
            kind = kind_from_plaid(str(a.type), str(a.subtype) if a.subtype else None, a.name, institution, self.cfg)
            aid = upsert_account(conn, source="plaid", source_account_id=a.account_id, name=a.name,
                                 kind=kind, institution=institution, mask=a.mask, connection_id=connection_id,
                                 meta={"official_name": a.official_name, "plaid_type": str(a.type),
                                       "plaid_subtype": str(a.subtype) if a.subtype else None})
            bal = a.balances.current
            if bal is not None:
                record_balance(conn, aid, as_of, float(bal),
                               float(a.balances.available) if a.balances.available is not None else None, "plaid")
            n += 1
        return n

    def _sync_transactions(self, conn, connection_id: str, token: str, cursor: str | None) -> dict[str, int]:
        from plaid.model.transactions_sync_request import TransactionsSyncRequest
        rules = compile_rules(self.cfg.flow_rules)
        added = modified = removed = 0
        has_more = True
        while has_more:
            req = TransactionsSyncRequest(access_token=token, cursor=cursor or "", count=500)
            resp = self.client().transactions_sync(req)
            store_raw(conn, self.name, "transactions_sync", connection_id,
                      {"added": len(resp.added), "modified": len(resp.modified), "removed": len(resp.removed),
                       "next_cursor": resp.next_cursor, "sample": [t.to_dict() for t in resp.added[:3]]})
            for t in list(resp.added) + list(resp.modified):
                self._upsert(conn, t, rules)
            added += len(resp.added)
            modified += len(resp.modified)
            for rm in resp.removed:
                remove_transaction(conn, "plaid", rm.transaction_id)
                removed += 1
            cursor = resp.next_cursor
            has_more = resp.has_more
        conn.execute("UPDATE connections SET cursor = ?, updated_at = ? WHERE id = ?", (cursor, now_iso(), connection_id))
        return {"added": added, "modified": modified, "removed": removed}

    def _upsert(self, conn, t, rules) -> None:
        aid = conn.execute("SELECT id FROM accounts WHERE source = 'plaid' AND source_account_id = ?",
                           (t.account_id,)).fetchone()
        if not aid:
            return
        pfc = getattr(t, "personal_finance_category", None)
        raw = None
        if pfc is not None:
            primary = getattr(pfc, "primary", None)
            detailed = getattr(pfc, "detailed", None)
            raw = f"{primary} > {detailed}" if primary and detailed else primary
        merchant = getattr(t, "merchant_name", None) or t.name
        upsert_transaction(
            conn, source="plaid", source_txn_id=t.transaction_id, account_id=aid["id"],
            posted_at=str(t.date), authorized_at=str(t.authorized_date) if getattr(t, "authorized_date", None) else None,
            amount=-float(t.amount), currency=t.iso_currency_code or "USD", description=t.name, merchant=merchant,
            category_raw=raw, pending=bool(t.pending), rules=rules,
            meta={"payment_channel": str(getattr(t, "payment_channel", "") or "")},
            replaces_source_txn_id=getattr(t, "pending_transaction_id", None))

    def _sync_holdings(self, conn, connection_id: str, token: str, as_of: str) -> int:
        from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
        resp = self.client().investments_holdings_get(InvestmentsHoldingsGetRequest(access_token=token))
        store_raw(conn, self.name, "investments_holdings_get", connection_id, resp.to_dict())
        secs = {s.security_id: s for s in resp.securities}
        by_account: dict[str, list[dict]] = {}
        for h in resp.holdings:
            s = secs.get(h.security_id)
            symbol = getattr(s, "ticker_symbol", None) if s else None
            name = (s.name if s and s.name else symbol) or h.security_id
            price = h.institution_price
            value = h.institution_value if h.institution_value is not None else (h.quantity * (price or 0))
            stype = str(getattr(s, "type", "") or "").lower() if s else ""
            asset_class = {"cash": "cash", "equity": "equity", "etf": "etf", "mutual fund": "fund",
                           "fixed income": "bond", "cryptocurrency": "crypto"}.get(stype, "other")
            by_account.setdefault(h.account_id, []).append(
                {"symbol": symbol, "description": name, "quantity": h.quantity, "price": price,
                 "value": value, "cost_basis": h.cost_basis, "asset_class": asset_class})
        n = 0
        for plaid_acct, rows in by_account.items():
            aid = conn.execute("SELECT id FROM accounts WHERE source='plaid' AND source_account_id=?",
                               (plaid_acct,)).fetchone()
            if aid:
                n += replace_positions(conn, aid["id"], as_of, rows, "plaid")
        return n


    def _sync_investment_transactions(self, conn, connection_id: str, token: str) -> dict[str, int]:
        """Buys, sells, dividends, fees and transfers inside investment accounts. Keyed by
        investment_transaction_id, so re-reading the window is idempotent."""
        from datetime import timedelta
        from plaid.model.investments_transactions_get_request import InvestmentsTransactionsGetRequest
        from plaid.model.investments_transactions_get_request_options import InvestmentsTransactionsGetRequestOptions
        end = date.today()
        first = conn.execute("SELECT 1 FROM transactions t JOIN accounts a ON a.id = t.account_id WHERE a.connection_id = ?"
                             " AND json_extract(t.meta, '$.investment') = 1 LIMIT 1", (connection_id,)).fetchone() is None
        start = end - timedelta(days=self.cfg.plaid.investment_txn_days if first else 45)
        accounts = {r["source_account_id"]: r["id"] for r in conn.execute(
            "SELECT id, source_account_id FROM accounts WHERE source = 'plaid' AND connection_id = ?", (connection_id,))}
        added = skipped = offset = 0
        total = None
        while total is None or offset < total:
            resp = self.client().investments_transactions_get(InvestmentsTransactionsGetRequest(
                access_token=token, start_date=start, end_date=end,
                options=InvestmentsTransactionsGetRequestOptions(count=500, offset=offset)))
            total = resp.total_investment_transactions
            secs = {s.security_id: s for s in resp.securities}
            if offset == 0:
                store_raw(conn, self.name, "investments_transactions_get", connection_id,
                          {"total": total, "sample": [t.to_dict() for t in resp.investment_transactions[:3]]})
            for t in resp.investment_transactions:
                aid = accounts.get(t.account_id)
                if not aid:
                    continue
                rec = investment_txn_record(t.to_dict(), (secs.get(t.security_id).to_dict() if secs.get(t.security_id) else None))
                _, status = upsert_transaction(conn, source="plaid", source_txn_id=rec["id"], account_id=aid,
                                               posted_at=rec["date"], amount=rec["amount"], currency=rec["currency"],
                                               description=rec["description"], merchant=rec["symbol"] or rec["description"],
                                               category=rec["category"], flow_type=rec["flow"], meta=rec["meta"])
                added += status == "inserted"
                skipped += status == "skipped"
            if not resp.investment_transactions:
                break
            offset += len(resp.investment_transactions)
        return {"investment_txns_added": added, "investment_txns_skipped": skipped}


_INV_FLOW = {"buy": "investment_buy", "sell": "investment_sell", "fee": "fee", "transfer": "transfer", "cancel": "unknown"}
_INV_CASH_SUBTYPE = {"dividend": "dividend", "qualified dividend": "dividend", "non-qualified dividend": "dividend",
                     "interest": "interest", "interest receivable": "interest", "long-term capital gain": "dividend",
                     "short-term capital gain": "dividend", "contribution": "transfer", "deposit": "transfer",
                     "withdrawal": "transfer", "tax": "tax", "tax withheld": "tax", "account fee": "fee",
                     "management fee": "fee", "fund fee": "fee", "legal fee": "fee", "transfer fee": "fee", "trust fee": "fee",
                     "margin expense": "fee", "miscellaneous fee": "fee", "dividend reinvestment": "investment_buy",
                     "interest reinvestment": "investment_buy"}


def investment_txn_record(t: dict[str, Any], sec: dict[str, Any] | None) -> dict[str, Any]:
    """Map a Plaid investment transaction to ledger fields. Plaid's amount is positive when cash
    leaves the account (a buy); the ledger is signed the other way."""
    typ, sub = str(t.get("type") or "").lower(), str(t.get("subtype") or "").lower()
    flow = _INV_CASH_SUBTYPE.get(sub) or _INV_FLOW.get(typ) or "unknown"
    symbol = (sec or {}).get("ticker_symbol")
    category = {"investment_buy": "Financial Services > Investment Trades", "investment_sell": "Financial Services > Investment Sales",
                "dividend": "Income > Dividends", "interest": "Income > Interest Earned", "fee": "Financial Services > Fees",
                "tax": "Financial Services > Tax Payment", "transfer": "Transfers > Internal Transfer"}.get(flow, "Uncategorized")
    return {"id": t["investment_transaction_id"], "date": str(t["date"])[:10], "amount": -float(t.get("amount") or 0),
            "currency": t.get("iso_currency_code") or "USD", "description": t.get("name") or f"{typ} {symbol or ''}".strip(),
            "symbol": symbol, "flow": flow, "category": category,
            "meta": {"investment": 1, "type": typ, "subtype": sub, "symbol": symbol, "security_name": (sec or {}).get("name"),
                     "quantity": t.get("quantity"), "price": t.get("price"), "fees": t.get("fees")}}


def _plaid_error(e: Exception) -> tuple[str, str]:
    body = getattr(e, "body", None)
    if body:
        try:
            d = json.loads(body)
            return d.get("error_code", "ERROR"), d.get("error_message", str(e))
        except Exception:  # noqa: BLE001
            pass
    return type(e).__name__, str(e)
