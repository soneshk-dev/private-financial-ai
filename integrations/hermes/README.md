# Using hermes-agent as the chat harness

homeai can hand the agent loop to a [hermes-agent](https://github.com/NousResearch/hermes-agent)
gateway instead of running its own. hermes brings persistent memory, skills,
context compaction and messaging channels (Telegram etc.); homeai keeps the
ledger, the tools, the profile and the dashboards. Both stay local.

## Wiring

1. Run homeai's MCP server over HTTP (`deploy/homeai-mcp.service`, port 5011).
2. In the hermes profile's `config.yaml`:

```yaml
mcp_servers:
  homeai:
    url: http://127.0.0.1:5011/mcp
    timeout: 180
platforms:
  api_server:
    enabled: true
    port: 9319          # matches llm.hermes_url in homeai's config
    key: <a random token, also HERMES_API_KEY in homeai's secrets_dir/hermes.conf>
model:
  provider: <a local OpenAI-compatible provider>
  default: <model>
```

3. Copy `skill/SKILL.md` into the profile's `skills/homeai-financial/` so the
   agent knows the tool conventions (signed amounts, `flow`, `transactions_v`).
4. In homeai's `config.yaml`:

```yaml
llm:
  backend: hermes
  hermes_url: http://127.0.0.1:9319/v1
  hermes_fallback_builtin: true    # use the builtin loop if the gateway is down
```

homeai passes its generated profile as the system message and its conversation
id as `X-Hermes-Session-Id`, so hermes keeps its own session memory per
conversation. Tool progress events from hermes are shown as tool chips in the
chat panel.
