---
name: homeai-financial
description: Answer questions about the household's finances using the homeai MCP tools (mcp_homeai_*). Use for any question about balances, net worth, spending, cash flow, budgets, transactions, positions, crypto, or data freshness.
---

# homeai financial data

## Tools (mcp_homeai_*)

| Tool | Use it for |
|---|---|
| `get_net_worth` | net worth, assets, liabilities, by class/entity, daily series |
| `get_accounts` | account list with kind, institution, entity, latest balance |
| `get_cashflow` | income / spending / taxes / loan payments / investing by month |
| `get_spending` | one month by category and top merchants |
| `get_budgets` | budget vs actual for a month |
| `search_transactions` | filter by date, account, flow, category, text |
| `get_positions` | holdings by account, allocation, cost basis |
| `get_crypto` | wallets, DeFi positions, Aave health factor |
| `get_connector_health` | is the data fresh; which connections need re-login |
| `get_schema` + `run_sql` | read-only SQL for anything the tools above cannot answer |
| `set_transaction_override`, `set_account` | corrections the user asks for |
| `run_sync` | pull fresh data now |

## Conventions

- **Amounts are signed.** Negative = money out. Liabilities are positive amounts owed.
- **Use `flow`, never category text, to decide what a transaction is.** `expense`, `fee`, `refund` = spending; `income`, `dividend`, `interest` = income; `transfer` = between the household's own accounts (never income or spending); `loan_payment`, `tax`, `investment_buy`, `investment_sell` as named; `unknown` = unclassified inflow.
- **SQL goes through `transactions_v`** (overrides applied). Columns: posted_at, account_name, account_kind, amount, description, merchant, category, category_l1, flow, entity, pending, transfer_group.
- Every number in an answer comes from a tool result in this conversation.
- Lead with the answer, then the figures; tables for lists.
- If `get_connector_health` shows errors or a stale connector, say so.

## When the MCP server is down

Say so and stop. Do not query databases directly; the ledger lives in homeai's vault and is only meant to be read through the tools.
