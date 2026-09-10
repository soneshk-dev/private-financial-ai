"""The daily job: connectors → transfer pairing → snapshot → prune."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..config import Config
from ..connectors.base import SyncResult, prune_raw, run_connector
from ..connectors.registry import build_connectors
from ..ledger.accounts import apply_overrides, ensure_manual_accounts
from ..ledger.snapshots import snapshot_day
from ..ledger.transactions import pair_transfers


def _due(conn: sqlite3.Connection, name: str, every_days: int) -> bool:
    row = conn.execute("SELECT last_success_at FROM connector_health WHERE connector = ?", (name,)).fetchone()
    if not row or not row["last_success_at"]:
        return True
    last = datetime.fromisoformat(row["last_success_at"])
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last >= timedelta(days=every_days)


def run_sync(conn: sqlite3.Connection, cfg: Config, only: list[str] | None = None, force: bool = False,
             as_of: str | None = None) -> dict[str, Any]:
    as_of = as_of or date.today().isoformat()
    conn.execute("BEGIN")
    ensure_manual_accounts(conn, cfg)
    conn.execute("COMMIT")

    results: list[SyncResult] = []
    for c in build_connectors(cfg):
        if only and c.name not in only:
            continue
        if c.name == "bitcoin" and not force and not _due(conn, c.name, cfg.bitcoin.every_days):
            results.append(SyncResult(c.name, skipped=True, detail={"reason": "not due"}))
            continue
        results.append(run_connector(c, conn, cfg, as_of))

    conn.execute("BEGIN")
    apply_overrides(conn, cfg)
    pairs = pair_transfers(conn, since=(date.today() - timedelta(days=120)).isoformat())
    snap = snapshot_day(conn, as_of)
    pruned = prune_raw(conn, keep_days=60)
    conn.execute("COMMIT")
    try:  # refresh the model context file; never fail the sync over it
        from ..llm.profile import write_generated
        write_generated(conn, cfg)
    except Exception:  # noqa: BLE001
        pass
    return {"as_of": as_of, "connectors": [r.as_dict() for r in results], "transfer_pairs": pairs,
            "snapshot": {k: snap[k] for k in ("assets", "liabilities", "net_worth")}, "raw_pruned": pruned}
