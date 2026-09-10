import json

from homeai.llm import agent
from homeai.llm.profile import generate
from homeai.llm.provider import ChatResult
from homeai.services.brief import daily_brief
from homeai.tools import registry
from tests.conftest import TODAY


class FakeProvider:
    """Scripted responses: first a tool call, then a final answer that echoes the tool result."""
    name = "fake"

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def model(self):
        return "fake-model"

    def chat(self, messages, tools=None, temperature=0.2, max_tokens=None):
        self.calls.append(messages)
        content, tool_calls = self.script.pop(0)
        return ChatResult(content=content, tool_calls=tool_calls, reasoning=None,
                          usage={"prompt_tokens": 10, "completion_tokens": 5, "seconds": 0.1})


def test_registry_schemas_are_valid_openai_tools():
    tools = registry.openai_tools()
    names = {t["function"]["name"] for t in tools}
    assert {"get_net_worth", "search_transactions", "run_sql", "set_transaction_override", "run_sync"} <= names
    for t in tools:
        assert t["type"] == "function" and t["function"]["parameters"]["type"] == "object"
    assert "run_sync" not in {t["function"]["name"] for t in registry.openai_tools(include_mutating=False)}


def test_run_sql_is_read_only(cfg, conn, seeded):
    out = registry.call_tool(conn, cfg, "run_sql", {"query": "SELECT flow, COUNT(*) n FROM transactions_v GROUP BY flow"})
    assert out["columns"] == ["flow", "n"] and len(out["rows"]) >= 5
    for bad in ("DELETE FROM transactions", "SELECT 1; DROP TABLE accounts", "PRAGMA table_info(accounts)",
                "ATTACH DATABASE 'x' AS y"):
        assert "error" in registry.call_tool(conn, cfg, "run_sql", {"query": bad})
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 17


def test_tools_over_services(cfg, conn, seeded):
    nw = registry.call_tool(conn, cfg, "get_net_worth", {"days": 30})
    assert nw["net_worth"] == 65000 - 301200 and "accounts_by_class" not in nw
    accts = registry.call_tool(conn, cfg, "get_accounts", {})
    assert len(accts) == 6 and all("latest_balance" in a for a in accts)
    tx = registry.call_tool(conn, cfg, "search_transactions", {"flow": "tax"})
    assert len(tx) == 1
    fixed = registry.call_tool(conn, cfg, "set_transaction_override", {"transaction_id": tx[0]["id"], "flow_type": "expense"})
    assert fixed["flow"] == "expense"
    assert "error" in registry.call_tool(conn, cfg, "set_transaction_override", {"transaction_id": "nope"}, allow_mutating=True)
    assert "error" in registry.call_tool(conn, cfg, "run_sync", {}, allow_mutating=False)
    acc = registry.call_tool(conn, cfg, "set_account", {"account_id": seeded["biz"], "kind": "savings"})
    assert acc["ok"] and conn.execute("SELECT kind FROM accounts WHERE id=?", (seeded["biz"],)).fetchone()[0] == "savings"


def test_agent_loop_with_fake_provider(cfg, conn, seeded):
    script = [
        ("", [{"id": "c1", "type": "function", "function": {"name": "get_net_worth", "arguments": json.dumps({"days": 7})}}]),
        ("Your net worth is -236,200.", []),
    ]
    fake = FakeProvider(script)
    events = list(agent.run(conn, cfg, "what is my net worth?", providers={"fake": fake}, provider_name="fake"))
    types = [e["type"] for e in events]
    assert types == ["conversation", "routing", "tool_call", "tool_result", "message", "done"]
    assert events[2]["name"] == "get_net_worth" and events[3]["error"] is False
    assert events[4]["content"].startswith("Your net worth")
    cid = events[0]["id"]
    conv = agent.get_conversation(conn, cid)
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant", "tool", "assistant"]
    # second turn replays only user + final assistant text, not the tool round
    fake2 = FakeProvider([("Still the same.", [])])
    list(agent.run(conn, cfg, "and now?", conversation_id=cid, providers={"fake": fake2}, provider_name="fake"))
    sent = fake2.calls[0]
    assert sent[0]["role"] == "system" and "Financial profile" in sent[0]["content"]
    assert [m["role"] for m in sent[1:]] == ["user", "assistant", "user"]
    assert agent.list_conversations(conn)[0]["id"] == cid
    assert agent.ask(conn, cfg, "x", providers={"fake": FakeProvider([("42", [])])}, provider_name="fake") == "42"


def test_agent_reports_provider_failure(cfg, conn, seeded):
    class Down:
        name = "down"

        def model(self):
            raise RuntimeError("connection refused")

    events = list(agent.run(conn, cfg, "hi", providers={"down": Down()}, provider_name="down"))
    assert events[-1]["type"] == "error"


def test_profile_and_brief(cfg, conn, seeded):
    text = generate(conn, cfg)
    assert "## Accounts (active)" in text and "Mortgage" in text and "## Data coverage" in text
    (cfg.private_dir / "profile.md").write_text("## Household\nTwo adults, two kids.")
    from homeai.llm.profile import load
    full = load(conn, cfg, regenerate=True)
    assert "Two adults" in full and (cfg.vault_dir / "profile.generated.md").exists()
    brief = daily_brief(conn, cfg, today=TODAY)          # yesterday = d(1): the pending Target purchase
    assert "Daily brief" in brief and "Net worth" in brief and "Target" in brief and "(pending)" in brief
    assert "$-236,200" not in brief and "-$236,200" in brief   # net worth formatting
