import json

from homeai.llm import agent
from homeai.llm.hermes import parse_sse
from homeai.llm.provider import ProviderError


def _sse(*events):
    return list(events)


def test_parse_sse_maps_hermes_stream_to_events():
    lines = [
        'data: {"id":"c1","model":"GLM","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}', "",
        "event: hermes.tool.progress",
        'data: {"tool":"mcp_homeai_get_net_worth","emoji":"x","label":"get_net_worth(days=7)","toolCallId":"t1","status":"running"}', "",
        "event: hermes.tool.progress",
        'data: {"tool":"mcp_homeai_get_net_worth","toolCallId":"t1","status":"completed"}', "",
        'data: {"id":"c1","model":"GLM","choices":[{"index":0,"delta":{"content":"Your net worth "},"finish_reason":null}]}', "",
        'data: {"id":"c1","model":"GLM","choices":[{"index":0,"delta":{"content":"is $1."},"finish_reason":null}]}', "",
        'data: {"id":"c1","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}', "",
        "data: [DONE]", "",
    ]
    ev = list(parse_sse(lines))
    assert [e["type"] for e in ev] == ["tool_call", "tool_result", "delta", "delta", "message"]
    assert ev[0]["name"] == "get_net_worth" and ev[0]["id"] == "t1"
    assert ev[-1] == {"type": "message", "content": "Your net worth is $1.", "model": "GLM"}


class FakeHermes:
    def __init__(self, ok=True):
        self.ok = ok
        self.seen = None

    def model(self):
        if not self.ok:
            raise ProviderError("hermes: gateway not reachable")
        return "GLM"

    def stream(self, messages, session_id=None):
        self.seen = (messages, session_id)
        yield {"type": "tool_call", "id": "t1", "name": "get_budgets", "arguments": {"_label": "get_budgets()"}}
        yield {"type": "tool_result", "id": "t1", "name": "get_budgets", "preview": "", "error": False}
        yield {"type": "delta", "content": "Over on Travel."}
        yield {"type": "message", "content": "Over on Travel.", "model": "GLM"}
        yield {"type": "done", "usage": {"prompt_tokens": 0, "completion_tokens": 0, "seconds": 1.0, "rounds": 1, "backend": "hermes"}}


def test_agent_relays_to_hermes_and_persists(cfg, conn, seeded):
    cfg.llm.backend = "hermes"
    h = FakeHermes()
    events = list(agent.run(conn, cfg, "budgets?", hermes=h))
    types = [e["type"] for e in events]
    assert types == ["conversation", "routing", "tool_call", "tool_result", "delta", "message", "done"]
    cid = events[0]["id"]
    assert h.seen[1] == cid and h.seen[0][0]["role"] == "system" and h.seen[0][-1]["content"] == "budgets?"
    conv = agent.get_conversation(conn, cid)
    assert conv["provider"] == "hermes" and conv["model"] == "GLM"
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant", "assistant"]
    assert conv["messages"][-1]["content"] == "Over on Travel."


def test_agent_falls_back_to_builtin_when_hermes_down(cfg, conn, seeded):
    from tests.test_agent import FakeProvider
    cfg.llm.backend = "hermes"
    fake = FakeProvider([("builtin answer", [])])
    events = list(agent.run(conn, cfg, "hi", hermes=FakeHermes(ok=False), providers={"ollama": fake}))
    assert any(e["type"] == "status" and "falling back" in e["message"] for e in events)
    assert events[-2]["type"] == "message" and events[-2]["content"] == "builtin answer"


def test_hermes_explicit_provider_name_selects_hermes(cfg, conn, seeded):
    events = list(agent.run(conn, cfg, "x", provider_name="hermes", hermes=FakeHermes()))
    assert events[1] == {"type": "routing", "provider": "hermes", "model": "GLM"}
