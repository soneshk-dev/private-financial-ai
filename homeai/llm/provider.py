from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import Config, LlmProvider


class ProviderError(RuntimeError):
    pass


@dataclass
class ChatResult:
    content: str
    tool_calls: list[dict[str, Any]]
    reasoning: str | None
    usage: dict[str, int]
    raw: dict[str, Any] = field(default_factory=dict)

    def as_message(self) -> dict[str, Any]:
        m: dict[str, Any] = {"role": "assistant", "content": self.content or None}
        if self.tool_calls:
            m["tool_calls"] = self.tool_calls
        return m


class OpenAICompatProvider:
    """Minimal chat-completions client with tool calling. Model 'auto' resolves to
    the first model the server lists (the Spark cluster changes models often)."""

    def __init__(self, spec: LlmProvider):
        self.spec = spec
        self.name = spec.name
        self._model: str | None = None if spec.model == "auto" else spec.model

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.spec.api_key}", "Content-Type": "application/json"}

    def models(self) -> list[str]:
        r = httpx.get(f"{self.spec.base_url.rstrip('/')}/models", headers=self._headers(), timeout=10)
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", [])]

    def model(self) -> str:
        if self._model is None:
            ids = self.models()
            if not ids:
                raise ProviderError(f"{self.name}: no models listed")
            self._model = ids[0]
        return self._model

    def reachable(self) -> bool:
        try:
            self.models()
            return True
        except Exception:  # noqa: BLE001
            return False

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
             temperature: float = 0.2, max_tokens: int | None = None) -> ChatResult:
        body: dict[str, Any] = {"model": self.model(), "messages": messages, "temperature": temperature,
                                "max_tokens": max_tokens or self.spec.max_tokens}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        t0 = time.time()
        try:
            r = httpx.post(f"{self.spec.base_url.rstrip('/')}/chat/completions", headers=self._headers(),
                           json=body, timeout=self.spec.timeout)
        except httpx.HTTPError as e:
            raise ProviderError(f"{self.name}: {e}") from e
        if r.status_code >= 400:
            raise ProviderError(f"{self.name}: HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            calls.append({"id": tc.get("id") or f"call_{len(calls)}", "type": "function",
                          "function": {"name": fn.get("name"), "arguments": fn.get("arguments") or "{}"}})
        usage = data.get("usage") or {}
        return ChatResult(content=msg.get("content") or "", tool_calls=calls,
                          reasoning=msg.get("reasoning_content") or msg.get("reasoning"),
                          usage={"prompt_tokens": usage.get("prompt_tokens", 0),
                                 "completion_tokens": usage.get("completion_tokens", 0),
                                 "seconds": round(time.time() - t0, 1)}, raw=data)


def build_providers(cfg: Config) -> dict[str, OpenAICompatProvider]:
    return {p.name: OpenAICompatProvider(p) for p in cfg.llm.providers}


def provider_status(cfg: Config) -> list[dict[str, Any]]:
    out = []
    hermes_default = cfg.llm.backend == "hermes"
    if hermes_default:
        from .hermes import HermesBackend
        h = HermesBackend(cfg)
        ok = h.reachable()
        model = None
        if ok:
            try:
                model = h.model()
            except ProviderError:
                model = None
        out.append({"name": "hermes", "base_url": cfg.llm.hermes_url, "reachable": ok, "model": model,
                    "default": True, "fallback": False})
    for p in build_providers(cfg).values():
        ok = p.reachable()
        out.append({"name": p.name, "base_url": p.spec.base_url, "reachable": ok,
                    "model": (p.model() if ok else None) if p.spec.model == "auto" else p.spec.model,
                    "default": (not hermes_default) and p.name == cfg.llm.default,
                    "fallback": p.name == cfg.llm.fallback or (hermes_default and p.name == cfg.llm.default)})
    return out
