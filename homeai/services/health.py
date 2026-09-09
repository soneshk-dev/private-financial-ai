from __future__ import annotations

import json
import sqlite3
from typing import Any


def status(conn: sqlite3.Connection) -> dict[str, Any]:
    connectors = []
    for r in conn.execute("SELECT * FROM connector_health ORDER BY connector"):
        d = dict(r)
        d["detail"] = json.loads(d["detail"]) if d.get("detail") else None
        connectors.append(d)
    connections = [dict(r) for r in conn.execute(
        "SELECT id, connector, institution, status, error_code, last_success_at FROM connections ORDER BY institution")]
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("accounts", "transactions", "positions", "balances_daily", "snapshots_daily")}
    latest = conn.execute("SELECT as_of, net_worth FROM snapshots_daily ORDER BY as_of DESC LIMIT 1").fetchone()
    version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    return {"schema_version": version, "connectors": connectors, "connections": connections, "counts": counts,
            "latest_snapshot": dict(latest) if latest else None}
