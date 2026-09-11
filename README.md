# homeai

A private, local-first personal finance ledger. Your data stays in a SQLite
file on your own machine. Connectors pull balances, positions and transactions
from providers you already use (Plaid, Fina/Fidelity, Zerion, Bitcoin xpubs);
a small API serves dashboards and, later, a local-model chat panel and MCP
tools.

Not financial advice. No cloud. No telemetry.

## What it does

- **Ledger core.** Accounts with a `kind` (checking, 401k, mortgage, crypto
  wallet, ...) and an `entity` (personal or a business). Transactions carry a
  deterministic `flow_type` (`expense`, `income`, `transfer`, `investment_buy`,
  `loan_payment`, `tax`, ...) so "spending" is a column, not a chain of `LIKE`
  filters. Daily balances and positions give you net worth over time.
- **Connectors.** Plaid (banks, cards, mortgages, brokerages via OAuth), Fina
  (Fidelity), Zerion (EVM wallets and DeFi), Bitcoin (xpub / multisig
  descriptors, addresses derived locally). Each is idempotent and records its
  own health. Pending card transactions are replaced when they post, not
  duplicated.
- **Read API.** Net worth, cash flow by month, spending by category, budgets,
  positions and allocation, crypto and Aave health factor, transaction search
  with overrides.
- **Backfill.** One command imports the previous Shah AI database.
- **Local model loop.** One agent loop over OpenAI-compatible local endpoints
  (a vLLM/TabbyAPI box, Ollama) with a tool registry generated from the
  services. Conversations persist; the system prompt is one generated profile
  plus a hand-written `private/profile.md`. No cloud models.
- **MCP server** exposing the same tools to Claude Code or any MCP client
  (`homeai mcp`, stdio or streamable HTTP, optional read-only mode).
- **Daily brief** over Telegram, computed deterministically from the ledger.
- **Plan.** Entities (personal plus each business) with per-entity P&L and a
  review queue for business charges on personal accounts; a runway projection
  from liquid reserves, burn rate and dated incomes; a transparent tax
  estimate (brackets, payments made, safe harbour, remaining schedule,
  bracket headroom); goals; threshold alerts over Telegram after each sync.
- **Dashboards.** A SvelteKit single-page app (`web/`) served by the API:
  overview with net worth over time, cash flow, spending with budgets and
  inline overrides, transactions, portfolio with allocation and Aave health,
  accounts and connector status, and a chat drawer over the local model.
  Charts follow a validated light/dark palette and thin-mark conventions.

## Layout

```
homeai/
  config.py          settings model; private overlay + secrets
  db.py              connection + numbered SQL migrations
  migrations/        0001_init.sql ...
  ledger/            accounts, balances/positions, transactions, classify, snapshots
  connectors/        plaid, fina, zerion, bitcoin (+ base with health/raw capture)
  services/          overview, cashflow, portfolio, health, brief (pure read functions)
  tools/registry.py  tool definitions + handlers over the services (chat loop and MCP share it)
  llm/               provider (OpenAI-compatible client), agent (the loop), profile (context file)
  mcp_server.py      MCP server generated from the registry
  notify/telegram.py Telegram sender
  api/app.py         FastAPI surface (+ /api/chat SSE, /link page for Plaid Link)
  jobs/sync.py       connectors → transfer pairing → snapshot → prune
  backfill/legacy.py import from the old main.db
  cli.py             homeai migrate | sync | snapshot | backfill | serve | ...
tests/               deterministic tests on a synthetic fixture DB
deploy/              systemd user units
scripts/             pre-commit guard for secrets and private words
```

## Private overlay

The repo is public. Everything personal lives in two places that are ignored
here:

| Where | What |
|---|---|
| `$HOMEAI_PRIVATE_DIR` (default `./private`) | `config.yaml`, later `profile.md`; normally its own private git repo cloned into this checkout |
| `$HOMEAI_VAULT_DIR` (default `~/homeai-vault`) | `ledger.db`, raw provider payloads, documents |
| `secrets_dir` (default `~/.home-ai-secrets`) | `plaid.conf`, `fina.conf`, `zerion.conf`, `bitcoin_xpubs.conf`, `plaid_encryption.key` |

Install the pre-commit guard so names, account numbers and keys cannot land in
a commit: `scripts/install-hooks.sh`. It reads an optional
`private/wordlist.txt` (one term per line).

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[all]"
mkdir -p private && cp config.example.yaml private/config.yaml   # edit it
homeai migrate
homeai backfill --from ~/home-ai/vault/databases/main.db          # optional, previous app
homeai sync
homeai networth
homeai serve            # http://127.0.0.1:5010/docs
homeai models           # which local endpoints are reachable
homeai chat "how much did I spend on restaurants last month?"
homeai brief --send     # Telegram daily brief (secrets_dir/telegram.conf)
homeai mcp              # MCP over stdio:  claude mcp add homeai -- ~/pfa/.venv/bin/homeai mcp
scripts/build-web.sh    # build the dashboards into web/build (needs Node 22); homeai serve then serves them at /
```

Front-end development: `cd web && npm run dev` (Vite proxies `/api` to the running API on port 5010).

Run tests with `pytest`.

## Flow types

| flow | meaning | counted as |
|---|---|---|
| expense, fee, refund | money spent (refund negative) | spending |
| income, dividend, interest | money earned | income |
| transfer | between your own accounts | excluded |
| investment_buy / investment_sell | securities bought / sold | investing |
| loan_payment | payment to a mortgage/HELOC/loan | debt service |
| tax | estimated and final tax payments | taxes |
| unknown | unclassified inflow | reviewed by hand |

Overrides on a row (`flow_type_override`, `category_override`) always win and
survive re-syncs and reclassification.

## License

MIT.
