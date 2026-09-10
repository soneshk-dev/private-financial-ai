"""The one context file.

``profile.generated.md`` (in the vault) is rebuilt from the ledger on every sync
and on demand; ``profile.md`` in the private dir is written by hand (household,
employment, goals, beliefs). The system prompt is the two concatenated.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date

from ..config import Config
from ..services import cashflow, health, overview


def _money(v) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "n/a"


def generate(conn: sqlite3.Connection, cfg: Config) -> str:
    today = date.today().isoformat()
    lines = [f"# Financial profile (generated {today})", "",
             "Figures below are snapshots; call tools for current numbers.", ""]
    nw = overview.net_worth(conn, 30)
    lines += ["## Net worth", f"- As of {nw['as_of']}: net {_money(nw['net_worth'])} = assets {_money(nw['assets'])}"
              f" - liabilities {_money(nw['liabilities'])}",
              "- By class: " + ", ".join(f"{k} {_money(v)}" for k, v in nw["by_class"].items()),
              "- By entity: " + ", ".join(f"{k} {_money(v)}" for k, v in nw["by_entity"].items()), ""]
    lines += ["## Accounts (active)", "| name | kind | institution | entity | balance | id |", "|---|---|---|---|---|---|"]
    for a in overview.accounts_summary(conn):
        lines.append(f"| {a['name']} | {a['kind']} | {a['institution'] or ''} | {a['entity']} | "
                     f"{_money(a['latest_balance'])} | {a['id']} |")
    lines.append("")
    cf = cashflow.monthly_cashflow(conn, 3)
    if cf:
        lines += ["## Recent cash flow (signed; spending negative)"]
        for r in cf:
            lines.append(f"- {r['month']}: income {_money(r['income'])}, spending {_money(r['spending'])},"
                         f" taxes {_money(r['taxes'])}, loan payments {_money(r['loan_payments'])},"
                         f" investing {_money(r['investing'])}")
        lines.append("")
    budgets = cashflow.budget_status(conn, date.today().strftime("%Y-%m"))
    if budgets:
        lines += ["## Budgets (this month)"]
        for b in budgets:
            lines.append(f"- {b['category']}: {_money(b['spent'])} of {_money(b['limit'])} ({b['status']})")
        lines.append("")
    h = health.status(conn)
    cov = conn.execute("SELECT source, MIN(posted_at) AS first, MAX(posted_at) AS last, COUNT(*) AS n"
                       " FROM transactions GROUP BY source").fetchall()
    lines += ["## Data coverage",
              *[f"- {r['source']}: {r['n']} transactions, {r['first']} to {r['last']}" for r in cov],
              *[f"- connector {c['connector']}: {c['status']}, last success {c['last_success_at'] or 'never'}"
                + (f", error: {c['last_error'][:80]}" if c.get('last_error') else "") for c in h["connectors"]],
              *[f"- connection {x['institution']}: {x['status']}" for x in h["connections"] if x["status"] not in ("active", "removed")],
              ""]
    if cfg.flow_rules:
        lines += ["## Classification rules", *[f"- /{r.pattern}/ → {r.flow_type}" for r in cfg.flow_rules], ""]
    return "\n".join(lines)


def write_generated(conn: sqlite3.Connection, cfg: Config) -> str:
    text = generate(conn, cfg)
    cfg.vault_dir.mkdir(parents=True, exist_ok=True)
    (cfg.vault_dir / "profile.generated.md").write_text(text)
    return text


def load(conn: sqlite3.Connection, cfg: Config, regenerate: bool = False) -> str:
    gen_path = cfg.vault_dir / "profile.generated.md"
    generated = gen_path.read_text() if gen_path.exists() and not regenerate else write_generated(conn, cfg)
    hand_path = cfg.private_dir / cfg.profile_file
    hand = hand_path.read_text() if hand_path.exists() else ""
    return generated + ("\n\n" + hand if hand.strip() else "")


def as_json(conn: sqlite3.Connection, cfg: Config) -> str:
    return json.dumps({"generated": generate(conn, cfg)})
