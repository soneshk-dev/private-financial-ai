"""The chat loop: system prompt (profile) + history + tools, iterate until the
model answers without tool calls. Yields events the API streams as SSE."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from ..config import Config
from ..db import now_iso
from ..tools import registry
from . import profile as profile_mod
from .provider import OpenAICompatProvider, ProviderError, build_providers

SYSTEM = """You are the household's private financial assistant. You run locally; nothing leaves this machine.

Rules:
- Every number you state must come from a tool result in this conversation. Never estimate balances or totals from memory.
- Amounts are signed: negative is money out. "Spending" means flow in (expense, fee, refund). Transfers between the household's own accounts are not income or spending. loan_payment is debt service, tax is tax.
- Liabilities (cards, mortgage, HELOC) are shown as positive amounts owed.
- Prefer the purpose-built tools; use get_schema then run_sql only for questions they cannot answer.
- Be concise and concrete: lead with the answer, then the supporting figures. Use tables for lists of accounts or transactions.
- If data looks stale or a connector has an error, say so.
- You may correct classifications with set_transaction_override / set_account when the user asks; confirm what you changed.
"""


def _system_prompt(conn: sqlite3.Connection, cfg: Config) -> str:
    now = datetime.now(ZoneInfo(cfg.timezone))
    prof = profile_mod.load(conn, cfg)
    return f"{SYSTEM}\nToday is {now.strftime('%A %Y-%m-%d %H:%M')} ({cfg.timezone}).\n\n{prof}"


# ---------------------------------------------------------------- persistence
def new_conversation(conn: sqlite3.Connection, title: str | None = None, provider: str | None = None) -> str:
    cid = "conv_" + uuid.uuid4().hex[:12]
    ts = now_iso()
    conn.execute("INSERT INTO conversations (id, title, provider, created_at, updated_at) VALUES (?,?,?,?,?)",
                 (cid, title, provider, ts, ts))
    return cid


def add_message(conn: sqlite3.Connection, cid: str, role: str, content: str | None, tool_calls=None,
                tool_call_id: str | None = None, name: str | None = None, usage=None) -> int:
    cur = conn.execute("INSERT INTO messages (conversation_id, role, content, tool_calls, tool_call_id, name, usage,"
                       " created_at) VALUES (?,?,?,?,?,?,?,?)",
                       (cid, role, content, json.dumps(tool_calls) if tool_calls else None, tool_call_id, name,
                        json.dumps(usage) if usage else None, now_iso()))
    conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now_iso(), cid))
    return cur.lastrowid


def history(conn: sqlite3.Connection, cid: str, limit: int = 30) -> list[dict[str, Any]]:
    """Replay only user turns and final assistant answers; tool rounds are not
    replayed (the model re-queries, which keeps figures fresh and context small)."""
    rows = conn.execute("SELECT role, content, tool_calls FROM messages WHERE conversation_id = ?"
                        " AND role IN ('user','assistant') ORDER BY id", (cid,)).fetchall()
    out = [{"role": r["role"], "content": r["content"] or ""} for r in rows
           if r["role"] == "user" or (r["role"] == "assistant" and not r["tool_calls"] and r["content"])]
    return out[-limit:]


def list_conversations(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS n"
                        " FROM conversations c ORDER BY updated_at DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def get_conversation(conn: sqlite3.Connection, cid: str) -> dict[str, Any] | None:
    c = conn.execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
    if not c:
        return None
    msgs = [dict(m) for m in conn.execute("SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (cid,))]
    for m in msgs:
        m["tool_calls"] = json.loads(m["tool_calls"]) if m.get("tool_calls") else None
        m["usage"] = json.loads(m["usage"]) if m.get("usage") else None
    return {**dict(c), "messages": msgs}


# ---------------------------------------------------------------- the loop
def run(conn: sqlite3.Connection, cfg: Config, user_message: str, conversation_id: str | None = None,
        provider_name: str | None = None, providers: dict[str, OpenAICompatProvider] | None = None,
        allow_mutating: bool = True, hermes=None) -> Iterator[dict[str, Any]]:
    """Run one chat turn. ``provider_name`` selects a builtin provider, or "hermes"."""
    use_hermes = (provider_name == "hermes") or (provider_name is None and cfg.llm.backend == "hermes")
    providers = providers or build_providers(cfg)
    order = [n for n in ((None if use_hermes else provider_name) or cfg.llm.default, cfg.llm.fallback)
             if n and n in providers]
    if not order and not use_hermes:
        yield {"type": "error", "message": f"no such provider: {provider_name or cfg.llm.default}"}
        return

    conn.execute("BEGIN")
    cid = conversation_id or new_conversation(conn, title=user_message[:80],
                                              provider="hermes" if use_hermes else order[0])
    if conversation_id and not conn.execute("SELECT 1 FROM conversations WHERE id = ?", (cid,)).fetchone():
        conn.execute("ROLLBACK")
        yield {"type": "error", "message": f"unknown conversation {cid}"}
        return
    add_message(conn, cid, "user", user_message)
    conn.execute("COMMIT")
    yield {"type": "conversation", "id": cid}

    messages: list[dict[str, Any]] = [{"role": "system", "content": _system_prompt(conn, cfg)}]
    messages += history(conn, cid, cfg.llm.history_messages)[:-1]  # everything before this user turn
    messages.append({"role": "user", "content": user_message})

    if use_hermes:
        from .hermes import HermesBackend
        backend = hermes or HermesBackend(cfg)
        try:
            model = backend.model()
            yield {"type": "routing", "provider": "hermes", "model": model}
            answer = ""
            for ev in backend.stream(messages, session_id=cid):
                if ev["type"] == "message":
                    answer = ev["content"]
                    conn.execute("BEGIN")
                    add_message(conn, cid, "assistant", answer)
                    conn.execute("UPDATE conversations SET model = ?, provider = 'hermes' WHERE id = ?",
                                 (ev.get("model") or model, cid))
                    conn.execute("COMMIT")
                elif ev["type"] == "tool_call":
                    conn.execute("BEGIN")
                    add_message(conn, cid, "assistant", None, tool_calls=[{"id": ev["id"], "type": "function",
                                 "function": {"name": ev["name"], "arguments": json.dumps(ev["arguments"])}}])
                    conn.execute("COMMIT")
                yield ev
            return
        except ProviderError as e:
            if not (cfg.llm.hermes_fallback_builtin and order):
                yield {"type": "error", "message": str(e)}
                return
            yield {"type": "status", "message": f"{e}; falling back to the builtin loop"}

    tools = registry.openai_tools(include_mutating=allow_mutating)

    provider = None
    for name in order:
        p = providers[name]
        try:
            model = p.model()
        except Exception as e:  # noqa: BLE001
            yield {"type": "status", "message": f"{name} unavailable ({e}); trying next"}
            continue
        provider = p
        yield {"type": "routing", "provider": name, "model": model}
        break
    if provider is None:
        yield {"type": "error", "message": "no model provider reachable"}
        return

    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0, "rounds": 0}
    for _ in range(cfg.llm.max_iterations):
        try:
            result = provider.chat(messages, tools, cfg.llm.temperature)
        except ProviderError as e:
            yield {"type": "error", "message": str(e)}
            return
        for k in ("prompt_tokens", "completion_tokens", "seconds"):
            total_usage[k] += result.usage.get(k, 0)
        total_usage["rounds"] += 1
        if result.reasoning:
            yield {"type": "reasoning", "content": result.reasoning[:2000]}
        total_usage["seconds"] = round(total_usage["seconds"], 1)
        if not result.tool_calls:
            conn.execute("BEGIN")
            add_message(conn, cid, "assistant", result.content, usage=total_usage)
            conn.execute("UPDATE conversations SET model = ? WHERE id = ?", (provider.model(), cid))
            conn.execute("COMMIT")
            yield {"type": "message", "content": result.content}
            yield {"type": "done", "usage": total_usage}
            return
        assistant_msg = result.as_message()
        messages.append(assistant_msg)
        conn.execute("BEGIN")
        add_message(conn, cid, "assistant", result.content or None, tool_calls=result.tool_calls)
        conn.execute("COMMIT")
        for tc in result.tool_calls:
            fn = tc["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_raw": fn.get("arguments")}
            yield {"type": "tool_call", "id": tc["id"], "name": fn["name"], "arguments": args}
            out = registry.call_tool(conn, cfg, fn["name"], args, allow_mutating=allow_mutating)
            text = registry.to_text(out)
            conn.execute("BEGIN")
            add_message(conn, cid, "tool", text, tool_call_id=tc["id"], name=fn["name"])
            conn.execute("COMMIT")
            messages.append({"role": "tool", "tool_call_id": tc["id"], "name": fn["name"], "content": text})
            yield {"type": "tool_result", "id": tc["id"], "name": fn["name"], "preview": text[:300],
                   "error": isinstance(out, dict) and "error" in out}
    yield {"type": "error", "message": f"stopped after {cfg.llm.max_iterations} tool rounds"}


def ask(conn: sqlite3.Connection, cfg: Config, question: str, **kw) -> str:
    """One-shot helper: returns the final answer text (or the error)."""
    answer = ""
    for ev in run(conn, cfg, question, **kw):
        if ev["type"] == "message":
            answer = ev["content"]
        elif ev["type"] == "error":
            answer = f"[error] {ev['message']}"
    return answer
