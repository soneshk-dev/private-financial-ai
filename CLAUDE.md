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

## Adding a read

Put the SQL in `homeai/services/*.py` as a pure function over a connection, expose it in `api/app.py`, add a test in `tests/test_services_api.py`. The MCP tools and chat layer (next phase) wrap the same functions.

## Commands

```
homeai migrate | sync [--only plaid,fina] [--force] | snapshot | backfill --from PATH
homeai accounts | health | networth | cashflow | spending --month YYYY-MM | reclassify | pair
homeai serve | homeai plaid link-token [--update ID] | plaid exchange TOKEN | plaid remove ID
```
