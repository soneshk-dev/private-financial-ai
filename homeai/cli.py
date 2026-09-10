"""homeai command line."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from .config import load_config
from .db import connect, migrate


def _json(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="homeai", description="private, local-first finance ledger")
    p.add_argument("--config", help="path to config.yaml (default: $HOMEAI_PRIVATE_DIR/config.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("migrate", help="create/upgrade the ledger schema")
    s = sub.add_parser("sync", help="run connectors, pair transfers, snapshot")
    s.add_argument("--only", help="comma-separated connector names")
    s.add_argument("--force", action="store_true", help="run connectors that are not due (bitcoin)")
    sub.add_parser("snapshot", help="write today's net-worth snapshot")
    b = sub.add_parser("backfill", help="import the previous Shah AI database")
    b.add_argument("--from", dest="src", required=True, help="path to old main.db")
    sub.add_parser("reclassify", help="recompute flow_type for all transactions (overrides kept)")
    sub.add_parser("pair", help="pair transfer legs")
    sub.add_parser("accounts", help="list accounts with latest balances")
    sub.add_parser("health", help="connector and database status")
    sub.add_parser("networth", help="latest snapshot")
    c = sub.add_parser("cashflow", help="monthly cash flow")
    c.add_argument("--months", type=int, default=12)
    sp = sub.add_parser("spending", help="spending by category for a month")
    sp.add_argument("--month", default=date.today().strftime("%Y-%m"))
    sv = sub.add_parser("serve", help="run the API")
    sv.add_argument("--host")
    sv.add_argument("--port", type=int)
    ch = sub.add_parser("chat", help="ask the local model one question (tools enabled)")
    ch.add_argument("message")
    ch.add_argument("--provider")
    ch.add_argument("--conversation")
    ch.add_argument("--events", action="store_true", help="print every event, not just the answer")
    sub.add_parser("models", help="local model providers and reachability")
    pr = sub.add_parser("profile", help="regenerate and print the model context file")
    pr.add_argument("--generated-only", action="store_true")
    br = sub.add_parser("brief", help="daily brief")
    br.add_argument("--send", action="store_true", help="send to Telegram")
    mc = sub.add_parser("mcp", help="run the MCP server (stdio by default)")
    mc.add_argument("--http", action="store_true")
    mc.add_argument("--port", type=int, default=5011)
    mc.add_argument("--readonly", action="store_true")
    pl = sub.add_parser("plaid", help="Plaid helpers")
    pls = pl.add_subparsers(dest="plaid_cmd", required=True)
    plt = pls.add_parser("link-token")
    plt.add_argument("--update", help="connection id for update mode")
    plt.add_argument("--redirect-uri")
    ple = pls.add_parser("exchange")
    ple.add_argument("public_token")
    plr = pls.add_parser("remove")
    plr.add_argument("connection_id")

    a = p.parse_args(argv)
    cfg = load_config(a.config)
    conn = connect(cfg.db_path)
    applied = migrate(conn)

    if a.cmd == "migrate":
        _json({"db": str(cfg.db_path), "applied": applied})
    elif a.cmd == "sync":
        from .jobs.sync import run_sync
        _json(run_sync(conn, cfg, only=a.only.split(",") if a.only else None, force=a.force))
    elif a.cmd == "snapshot":
        from .ledger.snapshots import snapshot_day
        conn.execute("BEGIN")
        out = snapshot_day(conn)
        conn.execute("COMMIT")
        _json({k: out[k] for k in ("as_of", "assets", "liabilities", "net_worth", "by_class")})
    elif a.cmd == "backfill":
        from .backfill.legacy import backfill
        from .ledger.accounts import apply_overrides
        from .ledger.snapshots import snapshot_day
        from .ledger.transactions import pair_transfers
        counts = backfill(conn, cfg, a.src)
        conn.execute("BEGIN")
        counts["overrides_applied"] = apply_overrides(conn, cfg)
        counts["transfer_pairs"] = pair_transfers(conn)
        snap = snapshot_day(conn)
        conn.execute("COMMIT")
        counts["net_worth"] = snap["net_worth"]
        _json(counts)
    elif a.cmd == "reclassify":
        from .ledger.classify import compile_rules
        from .ledger.transactions import reclassify_all
        conn.execute("BEGIN")
        n = reclassify_all(conn, compile_rules(cfg.flow_rules))
        conn.execute("COMMIT")
        _json({"reclassified": n})
    elif a.cmd == "pair":
        from .ledger.transactions import pair_transfers
        conn.execute("BEGIN")
        n = pair_transfers(conn)
        conn.execute("COMMIT")
        _json({"pairs": n})
    elif a.cmd == "accounts":
        from .services.overview import accounts_summary
        for r in accounts_summary(conn):
            bal = f"{r['latest_balance']:>14,.2f}" if r["latest_balance"] is not None else f"{'-':>14}"
            print(f"{r['id']}  {r['kind']:<16} {bal}  {r['institution'] or '':<22} {r['name']}")
    elif a.cmd == "health":
        from .services.health import status
        _json(status(conn))
    elif a.cmd == "networth":
        from .services.overview import net_worth
        out = net_worth(conn, 30)
        out.pop("series", None)
        out.pop("accounts_by_class", None)
        _json(out)
    elif a.cmd == "cashflow":
        from .services.cashflow import monthly_cashflow
        for r in monthly_cashflow(conn, a.months):
            print(f"{r['month']}  income {r['income']:>12,.0f}  spending {r['spending']:>12,.0f}  taxes {r['taxes']:>10,.0f}"
                  f"  loans {r['loan_payments']:>10,.0f}  investing {r['investing']:>12,.0f}  net {r['net']:>12,.0f}  n={r['n']}")
    elif a.cmd == "spending":
        from .services.cashflow import spending_by_category
        out = spending_by_category(conn, a.month)
        print(f"{a.month}: total {out['total']:,.2f}")
        for r in out["by_level1"]:
            print(f"  {r['category']:<22} {r['spent']:>12,.2f}  ({r['n']})")
    elif a.cmd == "serve":
        import uvicorn
        from .api.app import create_app
        uvicorn.run(create_app(cfg), host=a.host or cfg.api.host, port=a.port or cfg.api.port, log_level="info")
    elif a.cmd == "chat":
        from .llm import agent
        for ev in agent.run(conn, cfg, a.message, conversation_id=a.conversation, provider_name=a.provider):
            if a.events:
                print(json.dumps(ev, default=str)[:400])
            elif ev["type"] == "routing":
                print(f"[{ev['provider']} · {ev['model']}]", file=sys.stderr)
            elif ev["type"] == "tool_call":
                print(f"  → {ev['name']} {json.dumps(ev['arguments'])}", file=sys.stderr)
            elif ev["type"] == "message":
                print(ev["content"])
            elif ev["type"] == "error":
                print(f"error: {ev['message']}", file=sys.stderr)
            elif ev["type"] == "done":
                u = ev["usage"]
                print(f"[{u['rounds']} rounds, {u['prompt_tokens']}+{u['completion_tokens']} tokens, {u['seconds']}s]", file=sys.stderr)
    elif a.cmd == "models":
        from .llm.provider import provider_status
        _json(provider_status(cfg))
    elif a.cmd == "profile":
        from .llm import profile
        print(profile.write_generated(conn, cfg) if a.generated_only else profile.load(conn, cfg, regenerate=True))
    elif a.cmd == "brief":
        from .services.brief import daily_brief
        text = daily_brief(conn, cfg)
        print(text)
        if a.send:
            from .notify import telegram
            _json(telegram.send(cfg, text))
    elif a.cmd == "mcp":
        from . import mcp_server
        conn.close()
        if a.http:
            mcp_server.run_http(cfg, a.readonly, "127.0.0.1", a.port)
        else:
            mcp_server.run_stdio(cfg, a.readonly)
        return 0
    elif a.cmd == "plaid":
        from .connectors.plaid import PlaidConnector
        pc = PlaidConnector(cfg)
        if a.plaid_cmd == "link-token":
            _json(pc.link_token_for_update(conn, a.update, a.redirect_uri) if a.update
                  else pc.create_link_token(redirect_uri=a.redirect_uri))
        elif a.plaid_cmd == "exchange":
            conn.execute("BEGIN")
            out = pc.exchange_public_token(conn, a.public_token)
            conn.execute("COMMIT")
            _json(out)
        elif a.plaid_cmd == "remove":
            conn.execute("BEGIN")
            pc.remove_connection(conn, a.connection_id)
            conn.execute("COMMIT")
            _json({"removed": a.connection_id})
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
