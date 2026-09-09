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

## Layout

```
homeai/
  config.py          settings model; private overlay + secrets
  db.py              connection + numbered SQL migrations
  migrations/        0001_init.sql ...
  ledger/            accounts, balances/positions, transactions, classify, snapshots
  connectors/        plaid, fina, zerion, bitcoin (+ base with health/raw capture)
  services/          overview, cashflow, portfolio, health (pure read functions)
  api/app.py         FastAPI surface (+ /link page for Plaid Link)
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
```

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
