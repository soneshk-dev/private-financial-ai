from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from ..config import Config
from ..db import connect
from ..ledger.accounts import set_locked
from ..ledger.transactions import set_override
from ..services import business, cashflow, goals, health, overview, portfolio, runway, taxes

Handler = Callable[[sqlite3.Connection, Config, dict[str, Any]], Any]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    mutating: bool = False
    tags: list[str] = field(default_factory=list)

    def openai(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}


def _obj(props: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props or {}, "required": required or []}


_SQL_FORBIDDEN = re.compile(r"\b(ATTACH|DETACH|PRAGMA|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|VACUUM|REINDEX)\b", re.I)


def run_sql(conn: sqlite3.Connection, cfg: Config, args: dict[str, Any]) -> dict[str, Any]:
    """Read-only SELECT against the ledger, on a separate read-only connection."""
    q = (args.get("query") or "").strip().rstrip(";")
    if not q.upper().startswith(("SELECT", "WITH")) or _SQL_FORBIDDEN.search(q) or ";" in q:
        return {"error": "only a single SELECT statement is allowed"}
    ro = sqlite3.connect(f"file:{cfg.db_path}?mode=ro", uri=True, timeout=10)
    ro.row_factory = sqlite3.Row
    try:
        cur = ro.execute(q)
        rows = cur.fetchmany(int(args.get("limit") or 200))
        cols = [d[0] for d in cur.description] if cur.description else []
        return {"columns": cols, "rows": [list(r) for r in rows], "truncated": len(rows) >= int(args.get("limit") or 200)}
    except sqlite3.Error as e:
        return {"error": str(e)}
    finally:
        ro.close()


def _schema(conn, cfg, args) -> dict[str, Any]:
    out = {}
    for r in conn.execute("SELECT name, sql FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'"
                          " AND name NOT IN ('raw_sync','messages','conversations','connections','schema_migrations')"):
        out[r["name"]] = r["sql"]
    out["_notes"] = ("Read transactions through transactions_v (column `flow` has overrides applied; amounts are signed,"
                     " negative = money out). Spending = flow IN ('expense','fee','refund'). Liabilities are positive"
                     " balances on accounts with is_liability = 1.")
    return out


def _txn_override(conn, cfg, args) -> dict[str, Any]:
    from ..services import categories
    tid = args["transaction_id"]
    if not conn.execute("SELECT 1 FROM transactions WHERE id = ?", (tid,)).fetchone():
        return {"error": f"unknown transaction {tid}"}
    out: dict[str, Any] = {}
    if args.get("category"):
        try:
            out = categories.recategorize(conn, tid, args["category"], scope=args.get("scope") or "one",
                                          remember=bool(args.get("remember")), allow_new=bool(args.get("allow_new")))
        except ValueError as e:
            return {"error": str(e)}
    if args.get("flow_type") or args.get("entity"):
        conn.execute("BEGIN")
        set_override(conn, tid, flow_type=args.get("flow_type"), entity=args.get("entity"))
        conn.execute("COMMIT")
    row = conn.execute("SELECT id, description, amount, flow, category, entity FROM transactions_v WHERE id = ?", (tid,)).fetchone()
    return {**dict(row), **{k: v for k, v in out.items() if k in ("scope", "merchant", "affected", "rule_id")}}


def _categories(conn, cfg, args) -> dict[str, Any]:
    from ..services import categories
    return {t["level1"]: [s["name"] for s in t["subs"]] for t in categories.taxonomy(conn)}


def _account_set(conn, cfg, args) -> dict[str, Any]:
    fields = {k: args[k] for k in ("kind", "entity", "name", "is_active") if k in args and args[k] is not None}
    if not fields:
        return {"error": "nothing to set"}
    conn.execute("BEGIN")
    try:
        set_locked(conn, args["account_id"], **fields)
        conn.execute("COMMIT")
    except (KeyError, ValueError) as e:
        conn.execute("ROLLBACK")
        return {"error": str(e)}
    return {"ok": True, "account_id": args["account_id"], "set": fields}


def _sync(conn, cfg, args) -> dict[str, Any]:
    from ..jobs.sync import run_sync
    only = args.get("only")
    return run_sync(conn, cfg, only=only.split(",") if only else None, force=bool(args.get("force")))


def _brief(conn, cfg, args) -> dict[str, Any]:
    from ..services.brief import daily_brief
    return {"text": daily_brief(conn, cfg)}


TOOLS: list[Tool] = [
    Tool("get_net_worth", "Latest net worth with assets, liabilities, breakdown by asset class and entity, and a daily"
         " series for the last N days.", _obj({"days": {"type": "integer", "default": 90}}),
         lambda conn, cfg, a: _trim_series(overview.net_worth(conn, int(a.get("days") or 90)))),
    Tool("get_accounts", "All active accounts with kind, institution, entity and latest balance. Liabilities have"
         " is_liability = 1 and positive balances (amount owed).", _obj({"include_inactive": {"type": "boolean"}}),
         lambda conn, cfg, a: [_acct(x) for x in overview.accounts_summary(conn, active_only=not a.get("include_inactive"))]),
    Tool("get_cashflow", "Monthly cash flow: income, spending, taxes, loan payments, investing, transfers, net. Amounts are"
         " signed (spending negative).", _obj({"months": {"type": "integer", "default": 12},
                                              "entity": {"type": "string", "description": "personal or business:<slug>"}}),
         lambda conn, cfg, a: cashflow.monthly_cashflow(conn, int(a.get("months") or 12), a.get("entity"))),
    Tool("get_spending", "Spending for one month by level-1 category, full category and top merchants. Positive numbers"
         " are money spent.", _obj({"month": {"type": "string", "description": "YYYY-MM, default current month"},
                                   "entity": {"type": "string"}}),
         lambda conn, cfg, a: cashflow.spending_by_category(conn, a.get("month") or date.today().strftime("%Y-%m"), a.get("entity"))),
    Tool("get_budgets", "Budget status for a month: limit, spent, percent and status per category.",
         _obj({"month": {"type": "string"}}),
         lambda conn, cfg, a: cashflow.budget_status(conn, a.get("month") or date.today().strftime("%Y-%m"))),
    Tool("search_transactions", "Search transactions. Filters: date range, account_id, flow (expense, income, transfer,"
         " investment_buy, investment_sell, dividend, interest, loan_payment, tax, fee, refund, unknown), category"
         " (level-1 or full), free text q, entity. Returns newest first.",
         _obj({"start": {"type": "string"}, "end": {"type": "string"}, "account_id": {"type": "string"},
               "flow": {"type": "string"}, "category": {"type": "string"}, "q": {"type": "string"},
               "entity": {"type": "string"}, "limit": {"type": "integer", "default": 50}}),
         lambda conn, cfg, a: [_txn(t) for t in cashflow.search_transactions(
             conn, start=a.get("start"), end=a.get("end"), account_id=a.get("account_id"), flow=a.get("flow"),
             category=a.get("category"), q=a.get("q"), entity=a.get("entity"), limit=int(a.get("limit") or 50))]),
    Tool("get_positions", "Investment positions grouped by account with allocation by asset class, total value and"
         " known cost basis.", _obj(), lambda conn, cfg, a: portfolio.positions(conn)),
    Tool("get_crypto", "Crypto wallets and exchanges, DeFi protocol positions (supplied/borrowed) and the Aave V3 health"
         " factor with BTC liquidation price.", _obj(), lambda conn, cfg, a: portfolio.crypto(conn)),
    Tool("get_connector_health", "Data freshness: connector status, last success, errors, connection states, row counts.",
         _obj(), lambda conn, cfg, a: health.status(conn)),
    Tool("get_schema", "Table and view definitions for run_sql, with conventions.", _obj(), _schema),
    Tool("run_sql", "Run one read-only SELECT against the ledger (use get_schema first). Prefer transactions_v.",
         _obj({"query": {"type": "string"}, "limit": {"type": "integer", "default": 200}}, ["query"]), run_sql),
    Tool("get_daily_brief", "The daily briefing text (yesterday's expenses, month-to-date vs budget, net worth change,"
         " data issues).", _obj(), _brief),
    Tool("get_business", "Entities (personal and each business) with a P&L summary, and per-entity monthly P&L when"
         " `entity` is given.", _obj({"entity": {"type": "string"}, "months": {"type": "integer", "default": 12}}),
         lambda conn, cfg, a: (business.pnl(conn, a["entity"], int(a.get("months") or 12)) if a.get("entity")
                               else business.summary(conn, int(a.get("months") or 12)))),
    Tool("get_review_queue", "Transactions on personal accounts that look like business activity or large unexplained"
         " outflows, to be assigned an entity with set_transaction_override.", _obj({"months": {"type": "integer", "default": 6}}),
         lambda conn, cfg, a: business.review_queue(conn, int(a.get("months") or 6))),
    Tool("get_runway", "Liquid reserves, burn rate, expected incomes (with end dates) and a month-by-month projection"
         " of reserves; includes the month reserves would go negative, if any.", _obj(),
         lambda conn, cfg, a: runway.project(conn, cfg)),
    Tool("get_tax_estimate", "Estimated federal and state tax for the configured year from ledger income, payments made,"
         " remaining balance, safe-harbour test, quarterly schedule and Roth-conversion headroom. An estimate with"
         " listed caveats, not advice.", _obj(), lambda conn, cfg, a: taxes.estimate(conn, cfg)),
    Tool("get_goals", "Goals with current amount, target, percent complete, months left and needed monthly saving.",
         _obj(), lambda conn, cfg, a: goals.progress(conn)),
    Tool("get_categories", "The category taxonomy ('Level 1 > Sub') a transaction may be assigned to. Call before"
         " set_transaction_override with a category so the name matches exactly.", _obj(), _categories),
    Tool("set_transaction_override", "Correct a transaction's flow_type, category ('Level 1 > Sub' from get_categories)"
         " and/or entity (personal or business:<slug>). scope='merchant' recategorises every transaction from the same"
         " merchant; remember=true stores a merchant rule so future syncs match. Overrides persist across syncs.",
         _obj({"transaction_id": {"type": "string"}, "flow_type": {"type": "string"}, "category": {"type": "string"},
               "entity": {"type": "string"}, "scope": {"type": "string", "enum": ["one", "merchant"]},
               "remember": {"type": "boolean"}, "allow_new": {"type": "boolean"}}, ["transaction_id"]),
         _txn_override, mutating=True),
    Tool("set_account", "Set and lock an account's kind, entity (personal or business:<slug>), name or is_active.",
         _obj({"account_id": {"type": "string"}, "kind": {"type": "string"}, "entity": {"type": "string"},
               "name": {"type": "string"}, "is_active": {"type": "boolean"}}, ["account_id"]), _account_set, mutating=True),
    Tool("run_sync", "Run the data connectors now (optionally only some: plaid,fina,zerion,bitcoin) and refresh the"
         " net-worth snapshot.", _obj({"only": {"type": "string"}, "force": {"type": "boolean"}}), _sync, mutating=True),
]
BY_NAME = {t.name: t for t in TOOLS}


def openai_tools(include_mutating: bool = True) -> list[dict[str, Any]]:
    return [t.openai() for t in TOOLS if include_mutating or not t.mutating]


def call_tool(conn: sqlite3.Connection, cfg: Config, name: str, args: dict[str, Any] | None,
              allow_mutating: bool = True) -> Any:
    t = BY_NAME.get(name)
    if t is None:
        return {"error": f"unknown tool {name}"}
    if t.mutating and not allow_mutating:
        return {"error": f"tool {name} is disabled in read-only mode"}
    try:
        return t.handler(conn, cfg, args or {})
    except Exception as e:  # noqa: BLE001
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        return {"error": f"{type(e).__name__}: {e}"}


def to_text(result: Any, limit: int = 12000) -> str:
    s = json.dumps(result, default=str, separators=(",", ":"))
    return s if len(s) <= limit else s[:limit] + f'... [truncated {len(s) - limit} chars]'


def _trim_series(nw: dict[str, Any]) -> dict[str, Any]:
    s = nw.get("series") or []
    if len(s) > 60:  # weekly sample for long ranges
        nw["series"] = s[::max(1, len(s) // 60)]
    nw.pop("accounts_by_class", None)
    return nw


def _acct(a: dict[str, Any]) -> dict[str, Any]:
    return {k: a.get(k) for k in ("id", "name", "institution", "kind", "asset_class", "entity", "is_liability",
                                  "latest_balance", "balance_as_of", "source")}


def _txn(t: dict[str, Any]) -> dict[str, Any]:
    return {k: t.get(k) for k in ("id", "posted_at", "account_name", "amount", "description", "merchant",
                                  "category", "flow", "entity", "pending")}


def fresh_conn(cfg: Config) -> sqlite3.Connection:
    return connect(cfg.db_path)
