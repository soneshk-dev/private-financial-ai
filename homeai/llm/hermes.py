"""Hermes-agent as the chat harness.

homeai keeps the data, the tools (served to hermes over MCP), the profile and the
dashboards; hermes runs the agent loop and brings its own memory, skills,
compaction and messaging channels. This module relays a turn to the hermes
gateway's OpenAI-compatible endpoint and translates its SSE stream into homeai's
chat events, so the UI does not care which harness answered.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Iterable, Iterator

import httpx

from ..config import Config
from .provider import ProviderError

TOOL_PREFIX = re.compile(r"^mcp_{1,2}homeai_{1,2}")   # hermes names MCP tools mcp__<server>__<tool>


def parse_sse(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    """Turn a hermes chat-completions SSE byte stream into homeai events.

    hermes emits OpenAI chunks (``data: {...delta.content...}``), custom
    ``event: hermes.tool.progress`` events ({tool, label, toolCallId, status}),
    and ``data: [DONE]``. Yields: tool_call, tool_result, message, done.
    """
    event_name: str | None = None
    content: list[str] = []
    model: str | None = None
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            event_name = None
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            continue
        if event_name == "hermes.tool.progress":
            name = str(obj.get("tool") or "")
            short = TOOL_PREFIX.sub("", name)
            if obj.get("status") == "running":
                yield {"type": "tool_call", "id": obj.get("toolCallId"), "name": short,
                       "arguments": {"_label": obj.get("label")}}
            elif obj.get("status") == "completed":
                yield {"type": "tool_result", "id": obj.get("toolCallId"), "name": short, "preview": "", "error": False}
            continue
        model = model or obj.get("model")
        for ch in obj.get("choices") or []:
            delta = (ch.get("delta") or {}).get("content")
            if delta:
                content.append(delta)
                yield {"type": "delta", "content": delta}
            if ch.get("finish_reason") == "error":
                yield {"type": "error", "message": (ch.get("delta") or {}).get("content") or "hermes error"}
    yield {"type": "message", "content": "".join(content), "model": model}


class HermesBackend:
    name = "hermes"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.base = cfg.llm.hermes_url.rstrip("/")
        self.key = cfg.secret("hermes.conf", "HERMES_API_KEY", env="HERMES_API_KEY") or ""

    def _headers(self, session_id: str | None = None) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.key:
            h["Authorization"] = f"Bearer {self.key}"
        if session_id:
            h["X-Hermes-Session-Id"] = session_id
        return h

    def reachable(self) -> bool:
        try:
            r = httpx.get(f"{self.base}/health", headers=self._headers(), timeout=5)
            return r.status_code < 500
        except httpx.HTTPError:
            return False

    def model(self) -> str:
        try:
            r = httpx.get(f"{self.base}/models", headers=self._headers(), timeout=10)
            ids = [m.get("id") for m in (r.json().get("data") or [])] if r.status_code == 200 else []
            return ids[0] if ids else "hermes"
        except (httpx.HTTPError, ValueError):
            raise ProviderError(f"hermes: gateway not reachable at {self.base}")

    def stream(self, messages: list[dict[str, Any]], session_id: str | None = None) -> Iterator[dict[str, Any]]:
        body = {"model": "hermes", "messages": messages, "stream": True}
        t0 = time.time()
        try:
            with httpx.stream("POST", f"{self.base}/chat/completions", headers=self._headers(session_id),
                              json=body, timeout=httpx.Timeout(self.cfg.llm.hermes_timeout, connect=10)) as r:
                if r.status_code >= 400:
                    raise ProviderError(f"hermes: HTTP {r.status_code}: {r.read()[:300]!r}")
                yield from parse_sse(r.iter_lines())
        except httpx.HTTPError as e:
            raise ProviderError(f"hermes: {e}") from e
        yield {"type": "done", "usage": {"prompt_tokens": 0, "completion_tokens": 0, "seconds": round(time.time() - t0, 1),
                                          "rounds": 1, "backend": "hermes"}}
