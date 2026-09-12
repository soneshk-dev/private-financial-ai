# homeai — notes for coding agents

Read `README.md` first. This file covers the rules that are not obvious from the code.

## Non-negotiables

1. **This repo is public.** Nothing personal goes in tracked files: no names, employers, balances, account masks, addresses, keys. Personal configuration lives in `$HOMEAI_PRIVATE_DIR` (gitignored), data in `$HOMEAI_VAULT_DIR`, secrets in `secrets_dir`. If you need a personal string in code, it is a config field.
2. **Local only.** No cloud model calls in this codebase. Providers are the data connectors listed in `homeai/connectors/`; nothing else talks to the network.
3. **Every read goes through `transactions_v`** (overrides applied) and reads `flow`, never a `LIKE` on category text.
4. **Connectors are idempotent** and key rows by provider id (`source`, `source_txn_id` / `source_account_id`). Pending→posted uses `replaces_source_txn_id`. Never delete-and-reinsert transactions.
5. **Schema changes are migrations.** Add `homeai/migrations/000N_name.sql`; never `ALTER` at runtime.
6. **Tests are deterministic.** They build a synthetic DB via `tests/conftest.py`. No network, no real data. Run `pytest` before committing.

## Adding a connector

Implement `name`, `configured()`, `sync(conn, cfg, as_of) -> SyncResult`; write through `ledger.accounts.upsert_account`, `ledger.balances.record_balance` / `replace_positions`, `ledger.transactions.upsert_transaction`; call `store_raw` with the payload; register in `connectors/registry.py`; add a parse test with a synthetic payload.

## Categories

`services/categories.py` owns the taxonomy: level 1 is fixed (`MASTER_CATEGORIES`), sub-categories are the
provider mappings + `CURATED` + user-kept ones (settings `category_taxonomy_extra`). Every manual category
write goes through `validate_category` (unknown level 1 is refused; a new sub needs `allow_new`) and
`recategorize` (scope one|merchant, optional exact-match merchant rule). Inherited free-text names are
flagged `core: false` and merged with `rename_category`, which also repoints rules and budgets.

## Adding a read

Put the SQL in `homeai/services/*.py` as a pure function over a connection, expose it in `api/app.py`, add a test in `tests/test_services_api.py`. The MCP tools and chat layer (next phase) wrap the same functions.

## Adding a tool (chat + MCP)

Add a `Tool(...)` to `homeai/tools/registry.py` whose handler calls a service function. Mark `mutating=True` if it writes. That is the whole change: the chat loop and the MCP server read the registry. Add a case to `tests/test_agent.py`.

## Model context

The system prompt is `vault/profile.generated.md` (rebuilt on every sync from the ledger) followed by `private/profile.md` (hand-written household facts, goals, preferences). Keep the generated part structural; the model calls tools for numbers.

## Commands

```
homeai migrate | sync [--only plaid,fina] [--force] | snapshot | backfill --from PATH
homeai accounts | health | networth | cashflow | spending --month YYYY-MM | reclassify | pair
homeai serve | homeai plaid link-token [--update ID] | plaid exchange TOKEN | plaid remove ID
homeai chat "question" [--provider spark] [--events] | models | profile | brief [--send] | mcp [--http --port 5011] [--readonly]
homeai categories [--suggest [--apply]] | recategorize TXN "Level 1 > Sub" [--merchant] [--remember] [--allow-new] | category-rename OLD NEW
```
