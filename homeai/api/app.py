"""FastAPI read/write surface. Binds to localhost; put an authenticating proxy
(Cloudflare Access, Tailscale) in front for remote use."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__
from ..config import Config, load_config
from ..db import connect, migrate
from ..ledger.accounts import set_locked
from ..ledger.transactions import set_override
from ..services import cashflow, health, overview, portfolio


class AccountPatch(BaseModel):
    kind: str | None = None
    entity: str | None = None
    name: str | None = None
    is_active: bool | None = None


class TxnPatch(BaseModel):
    flow_type: str | None = None
    category: str | None = None
    entity: str | None = None


class Exchange(BaseModel):
    public_token: str


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    provider: str | None = None
    allow_mutating: bool = True


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or load_config()
    app = FastAPI(title="homeai", version=__version__)
    app.state.cfg = cfg
    with connect(cfg.db_path) as c:
        migrate(c)
    if cfg.access.team_domain and cfg.access.aud:
        from .access import AccessMiddleware
        app.add_middleware(AccessMiddleware, cfg=cfg)

    def db():
        conn = connect(cfg.db_path)
        try:
            yield conn
        finally:
            conn.close()

    @app.get("/api/health")
    def api_health(conn: sqlite3.Connection = Depends(db)):
        return {"version": __version__, **health.status(conn)}

    @app.get("/api/accounts")
    def api_accounts(all: bool = False, conn: sqlite3.Connection = Depends(db)):
        return overview.accounts_summary(conn, active_only=not all)

    @app.patch("/api/accounts/{account_id}")
    def api_account_patch(account_id: str, body: AccountPatch, conn: sqlite3.Connection = Depends(db)):
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(400, "nothing to update")
        try:
            conn.execute("BEGIN")
            set_locked(conn, account_id, **fields)
            conn.execute("COMMIT")
        except KeyError:
            conn.execute("ROLLBACK")
            raise HTTPException(404, "account not found")
        return {"ok": True, "locked": list(fields)}

    @app.get("/api/net-worth")
    def api_net_worth(days: int = Query(365, ge=1, le=3650), conn: sqlite3.Connection = Depends(db)):
        return overview.net_worth(conn, days)

    @app.get("/api/cashflow")
    def api_cashflow(months: int = Query(12, ge=1, le=120), entity: str | None = None,
                     conn: sqlite3.Connection = Depends(db)):
        return cashflow.monthly_cashflow(conn, months, entity)

    @app.get("/api/spending")
    def api_spending(month: str | None = None, entity: str | None = None, conn: sqlite3.Connection = Depends(db)):
        month = month or date.today().strftime("%Y-%m")
        return cashflow.spending_by_category(conn, month, entity)

    @app.get("/api/budgets")
    def api_budgets(month: str | None = None, conn: sqlite3.Connection = Depends(db)):
        return cashflow.budget_status(conn, month or date.today().strftime("%Y-%m"))

    @app.get("/api/transactions")
    def api_transactions(start: str | None = None, end: str | None = None, account_id: str | None = None,
                         flow: str | None = None, category: str | None = None, q: str | None = None,
                         entity: str | None = None, pending: bool = True, limit: int = 200, offset: int = 0,
                         conn: sqlite3.Connection = Depends(db)):
        return cashflow.search_transactions(conn, start=start, end=end, account_id=account_id, flow=flow,
                                            category=category, q=q, entity=entity, include_pending=pending,
                                            limit=limit, offset=offset)

    @app.patch("/api/transactions/{txn_id}")
    def api_txn_patch(txn_id: str, body: TxnPatch, conn: sqlite3.Connection = Depends(db)):
        if not conn.execute("SELECT 1 FROM transactions WHERE id = ?", (txn_id,)).fetchone():
            raise HTTPException(404, "transaction not found")
        conn.execute("BEGIN")
        set_override(conn, txn_id, flow_type=body.flow_type, category=body.category, entity=body.entity)
        conn.execute("COMMIT")
        return {"ok": True}

    # --- Plan: business, runway, taxes, goals -----------------------------------
    from ..services import business, goals, runway, taxes

    @app.get("/api/entities")
    def api_entities(months: int = 12, conn: sqlite3.Connection = Depends(db)):
        return business.summary(conn, months)

    @app.get("/api/business/pnl")
    def api_business_pnl(entity: str, months: int = 12, conn: sqlite3.Connection = Depends(db)):
        return business.pnl(conn, entity, months)

    @app.get("/api/business/review")
    def api_business_review(months: int = 6, conn: sqlite3.Connection = Depends(db)):
        return business.review_queue(conn, months)

    @app.get("/api/runway")
    def api_runway(conn: sqlite3.Connection = Depends(db)):
        return runway.project(conn, cfg)

    @app.get("/api/tax")
    def api_tax(conn: sqlite3.Connection = Depends(db)):
        return taxes.estimate(conn, cfg)

    @app.get("/api/goals")
    def api_goals(conn: sqlite3.Connection = Depends(db)):
        return goals.progress(conn)

    @app.get("/api/positions")
    def api_positions(conn: sqlite3.Connection = Depends(db)):
        return portfolio.positions(conn)

    @app.get("/api/crypto")
    def api_crypto(conn: sqlite3.Connection = Depends(db)):
        return portfolio.crypto(conn)

    @app.post("/api/sync")
    def api_sync(only: str | None = None, force: bool = False, conn: sqlite3.Connection = Depends(db)):
        from ..jobs.sync import run_sync
        return run_sync(conn, cfg, only=only.split(",") if only else None, force=force)

    # --- Plaid Link -------------------------------------------------------------
    @app.post("/api/plaid/link-token")
    def api_plaid_link_token(connection_id: str | None = None, redirect_uri: str | None = None):
        from ..connectors.plaid import PlaidConnector
        p = PlaidConnector(cfg)
        if not p.configured():
            raise HTTPException(503, "Plaid not configured")
        with connect(cfg.db_path) as conn:
            if connection_id:
                return p.link_token_for_update(conn, connection_id, redirect_uri)
        return p.create_link_token(redirect_uri=redirect_uri)

    @app.post("/api/plaid/exchange")
    def api_plaid_exchange(body: Exchange, conn: sqlite3.Connection = Depends(db)):
        from ..connectors.plaid import PlaidConnector
        p = PlaidConnector(cfg)
        conn.execute("BEGIN")
        try:
            out = p.exchange_public_token(conn, body.public_token)
            conn.execute("COMMIT")
        except Exception as e:  # noqa: BLE001
            conn.execute("ROLLBACK")
            raise HTTPException(502, str(e))
        return out

    @app.delete("/api/plaid/connections/{connection_id}")
    def api_plaid_remove(connection_id: str, conn: sqlite3.Connection = Depends(db)):
        from ..connectors.plaid import PlaidConnector
        conn.execute("BEGIN")
        PlaidConnector(cfg).remove_connection(conn, connection_id)
        conn.execute("COMMIT")
        return {"ok": True}

    # --- Chat ---------------------------------------------------------------------
    @app.get("/api/models")
    def api_models():
        from ..llm.provider import provider_status
        return provider_status(cfg)

    @app.get("/api/conversations")
    def api_conversations(conn: sqlite3.Connection = Depends(db)):
        from ..llm import agent
        return agent.list_conversations(conn)

    @app.get("/api/conversations/{cid}")
    def api_conversation(cid: str, conn: sqlite3.Connection = Depends(db)):
        from ..llm import agent
        c = agent.get_conversation(conn, cid)
        if not c:
            raise HTTPException(404, "conversation not found")
        return c

    @app.delete("/api/conversations/{cid}")
    def api_conversation_delete(cid: str, conn: sqlite3.Connection = Depends(db)):
        conn.execute("BEGIN")
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (cid,))
        n = conn.execute("DELETE FROM conversations WHERE id = ?", (cid,)).rowcount
        conn.execute("COMMIT")
        return {"deleted": n}

    @app.post("/api/chat")
    def api_chat(body: ChatRequest):
        """Server-sent events: conversation, routing, reasoning, tool_call, tool_result, message, done, error."""
        from ..llm import agent

        def gen():
            # Run the turn on a worker thread and emit an SSE comment every 15 s while
            # waiting, so reverse proxies (Cloudflare's 100 s idle limit) keep the stream open.
            import queue
            import threading
            q: queue.Queue = queue.Queue()

            def work():
                conn = connect(cfg.db_path)
                try:
                    for ev in agent.run(conn, cfg, body.message, conversation_id=body.conversation_id,
                                        provider_name=body.provider, allow_mutating=body.allow_mutating):
                        q.put(ev)
                except Exception as e:  # noqa: BLE001
                    q.put({"type": "error", "message": f"{type(e).__name__}: {e}"})
                finally:
                    conn.close()
                    q.put(None)

            threading.Thread(target=work, daemon=True).start()
            while True:
                try:
                    ev = q.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                if ev is None:
                    break
                yield f"event: {ev['type']}\ndata: {json.dumps(ev, default=str)}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/chat/ask")
    def api_chat_ask(body: ChatRequest, conn: sqlite3.Connection = Depends(db)):
        """Non-streaming convenience: returns the final answer."""
        from ..llm import agent
        events = list(agent.run(conn, cfg, body.message, conversation_id=body.conversation_id,
                                provider_name=body.provider, allow_mutating=body.allow_mutating))
        answer = next((e["content"] for e in reversed(events) if e["type"] == "message"), None)
        err = next((e["message"] for e in events if e["type"] == "error"), None)
        return {"conversation_id": next((e["id"] for e in events if e["type"] == "conversation"), None),
                "answer": answer, "error": err,
                "tools": [e["name"] for e in events if e["type"] == "tool_call"],
                "usage": next((e["usage"] for e in events if e["type"] == "done"), None)}

    @app.get("/api/brief")
    def api_brief(conn: sqlite3.Connection = Depends(db)):
        from ..services.brief import daily_brief
        return {"text": daily_brief(conn, cfg)}

    @app.get("/api/profile")
    def api_profile(regenerate: bool = False, conn: sqlite3.Connection = Depends(db)):
        from ..llm import profile
        return {"text": profile.load(conn, cfg, regenerate=regenerate)}

    @app.get("/link", response_class=HTMLResponse)
    def link_page(connection_id: str | None = None):
        """Minimal Plaid Link page: new connection, or update mode for ?connection_id=."""
        return LINK_HTML.replace("__CONNECTION_ID__", connection_id or "")

    # --- Front end (SvelteKit build in web/build): static files + SPA fallback ----
    web_dir = Path(os.environ.get("HOMEAI_WEB_DIR") or Path(__file__).resolve().parents[2] / "web" / "build")
    if web_dir.is_dir():
        app.mount("/_app", StaticFiles(directory=web_dir / "_app"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            candidate = (web_dir / path).resolve()
            if path and candidate.is_file() and str(candidate).startswith(str(web_dir.resolve())):
                return FileResponse(candidate)
            return FileResponse(web_dir / "index.html")

    return app


LINK_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>homeai · link an institution</title>
<script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
<style>body{font-family:system-ui;margin:3rem;max-width:40rem}button{font-size:1rem;padding:.6rem 1rem}pre{background:#f4f4f4;padding:1rem}</style>
</head><body><h1>Link an institution</h1>
<p id="mode"></p><button id="go">Open Plaid Link</button><pre id="out"></pre>
<script>
const cid = "__CONNECTION_ID__";
document.getElementById('mode').textContent = cid ? 'Update mode for connection ' + cid : 'New connection';
document.getElementById('go').onclick = async () => {
  const out = document.getElementById('out');
  const r = await fetch('/api/plaid/link-token' + (cid ? '?connection_id=' + encodeURIComponent(cid) : ''), {method:'POST'});
  const j = await r.json();
  if (!j.link_token) { out.textContent = JSON.stringify(j, null, 2); return; }
  const handler = Plaid.create({token: j.link_token, onSuccess: async (public_token) => {
    if (cid) { out.textContent = 'Updated. Run a sync.'; return; }
    const x = await fetch('/api/plaid/exchange', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({public_token})});
    out.textContent = JSON.stringify(await x.json(), null, 2);
  }, onExit: (err) => { if (err) out.textContent = JSON.stringify(err, null, 2); }});
  handler.open();
};
</script></body></html>"""


app = None  # created lazily by `homeai serve`
