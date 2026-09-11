import sqlite3

from homeai.backfill.legacy import backfill
from homeai.connectors.fina import FinaConnector, asset_class_from_name
from homeai.connectors.zerion import ZerionConnector
from homeai.connectors.bitcoin import parse_descriptor, is_descriptor


def test_fina_parse_transactions_both_layouts():
    # ids are opaque tokens (not UUIDs); dates carry a time part
    new = ("jZbDJ0ov73I5OROpqpAdiyw9KPZXmJiQrJkdD,2026-08-31T00:00:00.000Z,DIVIDEND RECEIVED FIDELITY MMKT,,acct-x,459.33,other income,USD,,false,false\n"
           "rOJk9K4xnrho7d7n8nARhnjgxQoPK3UKpzjJE,2026-08-31T00:00:00.000Z,DIRECT DEBIT ATT PAYMENT (Cash),ATT,acct-x,-55,bills & utilities,USD,,false,false\n"
           "bad,row\n")
    rows = FinaConnector.parse_transactions(new)
    assert len(rows) == 2 and rows[0]["amount"] == 459.33 and rows[1]["merchant"] == "ATT" and rows[1]["date"] == "2026-08-31"
    assert rows[0]["id"] == "jZbDJ0ov73I5OROpqpAdiyw9KPZXmJiQrJkdD"
    old = "2025-12-01,PAYCHECK,ACME,acct-y,5000,primary paycheck,USD,\n"
    rows = FinaConnector.parse_transactions(old)
    assert rows[0]["amount"] == 5000 and rows[0]["account_id"] == "acct-y" and len(rows[0]["id"]) == 32


def test_fina_balances_new_and_old_keys():
    data = [{"name": "p", "accounts": [{"id": "a", "name": "401k", "balance": 1.0, "institute": "Fidelity"}, None]},
            {"name": "q", "balances": [{"id": "b", "name": "IRA", "balance": 2.0, "institute": "Fidelity"}]}]
    out = FinaConnector.parse_balances(data)
    assert [o["id"] for o in out] == ["a", "b"]
    assert asset_class_from_name("FIDELITY GOVERNMENT MONEY MARKET") == "cash"
    assert asset_class_from_name("ISHARES BITCOIN TRUST ETF") == "etf"


def test_fina_legacy_rekey_and_txn_since(cfg, conn, seeded):
    from homeai.connectors.fina import find_legacy_id
    from homeai.ledger.accounts import set_locked
    from homeai.ledger.transactions import txn_id, upsert_transaction
    brok = seeded["brok"]
    conn.execute("BEGIN")
    # a row as the backfill wrote it (synthetic id) …
    upsert_transaction(conn, source="fina", source_txn_id="fina_2026-09-01_acct_12.34_abcd1234", account_id=brok,
                       posted_at="2026-09-01", amount=12.34, description="DIVIDEND RECEIVED X", category_raw="other income")
    legacy = find_legacy_id(conn, brok, "2026-09-01", 12.34, "DIVIDEND RECEIVED X")
    assert legacy == "fina_2026-09-01_acct_12.34_abcd1234"
    # … arrives from the live feed under Fina's id → re-keyed, not duplicated
    tid, status = upsert_transaction(conn, source="fina", source_txn_id="LIVEID123", account_id=brok, posted_at="2026-09-01",
                                     amount=12.34, description="DIVIDEND RECEIVED X", category_raw="other income",
                                     replaces_source_txn_id=legacy)
    assert status == "replaced" and tid == txn_id("fina", "LIVEID123")
    assert conn.execute("SELECT COUNT(*) FROM transactions WHERE description='DIVIDEND RECEIVED X'").fetchone()[0] == 1
    # cutover date: rows before it are skipped
    set_locked(conn, brok, txn_since="2026-09-10")
    _, st = upsert_transaction(conn, source="fina", source_txn_id="OLD1", account_id=brok, posted_at="2026-09-05",
                               amount=-5, description="OLD", category_raw="groceries")
    _, st2 = upsert_transaction(conn, source="fina", source_txn_id="NEW1", account_id=brok, posted_at="2026-09-12",
                                amount=-5, description="NEW", category_raw="groceries")
    conn.execute("COMMIT")
    assert st == "skipped" and st2 == "inserted"
    assert conn.execute("SELECT COUNT(*) FROM transactions WHERE description IN ('OLD','NEW')").fetchone()[0] == 1


def test_zerion_normalize_drops_receipts_and_signs_loans():
    positions = [
        {"attributes": {"value": 1000, "position_type": "wallet", "fungible_info": {"symbol": "ETH", "name": "Ether"},
                        "quantity": {"float": 0.5}, "price": 2000, "flags": {"displayable": True}},
         "relationships": {"chain": {"data": {"id": "ethereum"}}}},
        {"attributes": {"value": 500, "position_type": "wallet", "fungible_info": {"symbol": "aEthWBTC"},
                        "quantity": {"float": 0.01}, "flags": {"displayable": False}}, "relationships": {}},
        {"attributes": {"value": 500, "position_type": "deposit", "protocol": "Aave V3",
                        "fungible_info": {"symbol": "WBTC"}, "quantity": {"float": 0.01}, "price": 50000},
         "relationships": {"chain": {"data": {"id": "ethereum"}}}},
        {"attributes": {"value": 200, "position_type": "loan", "protocol": "Aave V3",
                        "fungible_info": {"symbol": "GHO"}, "quantity": {"float": 200}, "price": 1},
         "relationships": {"chain": {"data": {"id": "ethereum"}}}},
    ]
    d = ZerionConnector.normalize(positions, "ethereum")
    assert [t["symbol"] for t in d["tokens"]] == ["ETH"] and d["token_total"] == 1000
    assert len(d["protocols"]) == 1
    p = d["protocols"][0]
    assert p["protocol_slug"] == "aave-v3" and p["value"] == 300 and d["defi_total"] == 300
    assert {x["meta_type"] for x in p["details"]} == {"SUPPLIED", "BORROWED"}
    assert next(x for x in p["details"] if x["meta_type"] == "BORROWED")["value"] == 200


def test_bitcoin_descriptor_parse():
    desc = "wsh(sortedmulti(2,[aaaa1111/48'/0'/0'/2']zpub6A1/<0;1>/*,[bbbb2222/48'/0'/0'/2']zpub6B2/<0;1>/*))"
    assert is_descriptor(desc)
    info = parse_descriptor(desc)
    assert info["type"] == "p2wsh" and info["is_multisig"] and info["threshold"] == 2 and info["bip389"]
    assert [x["xpub"] for x in info["xpubs"]] == ["zpub6A1", "zpub6B2"]
    assert not is_descriptor("zpub6rFR7y4Q2Aij")


OLD_DDL = """
CREATE TABLE plaid_items (item_id TEXT PRIMARY KEY, access_token TEXT, institution_id TEXT, institution_name TEXT,
  status TEXT, error_code TEXT, error_message TEXT, transactions_cursor TEXT, last_sync_at TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE plaid_accounts (plaid_account_id TEXT PRIMARY KEY, item_id TEXT, local_account_id TEXT, account_name TEXT,
  official_name TEXT, account_type TEXT, account_subtype TEXT, mask TEXT, current_balance REAL, available_balance REAL,
  is_active INTEGER, created_at TEXT);
CREATE TABLE investment_accounts (account_id TEXT PRIMARY KEY, account_number TEXT, account_name TEXT, institution TEXT,
  account_type TEXT, is_taxable INTEGER, is_active INTEGER, created_at TEXT, last_updated TEXT, fina_account_id TEXT,
  last_synced TEXT, fina_balance REAL);
CREATE TABLE holdings (holding_id TEXT PRIMARY KEY, account_id TEXT, symbol TEXT, cusip TEXT, description TEXT,
  quantity REAL, cost_basis_total REAL, cost_basis_per_share REAL, current_price REAL, current_value REAL,
  asset_type TEXT, is_cash INTEGER, last_updated TEXT);
CREATE TABLE crypto_wallets (wallet_id TEXT PRIMARY KEY, wallet_name TEXT, chain TEXT, address TEXT, is_active INTEGER, last_synced TEXT, created_at TEXT);
CREATE TABLE crypto_balances (balance_id TEXT PRIMARY KEY, wallet_id TEXT, token_symbol TEXT, token_address TEXT, balance REAL, balance_usd REAL, last_updated TEXT);
CREATE TABLE defi_positions (position_id TEXT PRIMARY KEY, wallet_id TEXT, protocol TEXT, protocol_slug TEXT, network TEXT, balance_usd REAL, last_updated TEXT);
CREATE TABLE defi_position_details (detail_id TEXT PRIMARY KEY, position_id TEXT, wallet_id TEXT, protocol TEXT, protocol_slug TEXT,
  network TEXT, meta_type TEXT, token_symbol TEXT, token_balance REAL, balance_usd REAL, token_price REAL, contract_address TEXT, last_updated TEXT);
CREATE TABLE bitcoin_wallets (wallet_id TEXT PRIMARY KEY, wallet_name TEXT, xpub_reference TEXT, derivation_path TEXT,
  address_type TEXT, total_balance_btc REAL, total_balance_usd REAL, address_count INTEGER, last_synced TEXT, created_at TEXT);
CREATE TABLE accounts (account_id TEXT PRIMARY KEY, institution TEXT, account_type TEXT, nickname TEXT, is_active INTEGER,
  schema_version INTEGER, balance REAL, plaid_account_id TEXT, csv_cutoff_date TEXT, live_source TEXT);
CREATE TABLE transactions (txn_id TEXT PRIMARY KEY, txn_date TEXT, description TEXT, merchant TEXT, amount REAL, currency TEXT,
  category_raw TEXT, category_normalized TEXT, account_id TEXT, source_file_id TEXT, is_duplicate INTEGER, created_at TEXT,
  schema_version INTEGER, duplicate_of_txn_id TEXT, is_transfer INTEGER, transfer_pair_id TEXT, plaid_transaction_id TEXT,
  pending INTEGER, payment_channel TEXT, personal_finance_category_primary TEXT, personal_finance_category_detailed TEXT, source_type TEXT);
CREATE TABLE category_overrides (override_id TEXT PRIMARY KEY, txn_id TEXT, original_category TEXT, new_category TEXT, reason TEXT, created_at TEXT);
CREATE TABLE budgets (budget_id INTEGER PRIMARY KEY, category_normalized TEXT, category_level1 TEXT, monthly_limit REAL,
  effective_from TEXT, effective_until TEXT, is_active INTEGER, alert_threshold REAL, created_at TEXT, updated_at TEXT);
CREATE TABLE category_rules (id INTEGER PRIMARY KEY, merchant_pattern TEXT, category_level1 TEXT, category_full TEXT,
  confidence REAL, rule_type TEXT, created_at TEXT, last_used TEXT, usage_count INTEGER, manually_verified INTEGER);
CREATE TABLE ticker_mappings (description_pattern TEXT PRIMARY KEY, ticker TEXT, notes TEXT, created_at TEXT);
"""


def test_backfill_from_old_schema(tmp_path, cfg, conn):
    old_path = tmp_path / "old.db"
    o = sqlite3.connect(old_path)
    o.executescript(OLD_DDL)
    o.execute("INSERT INTO plaid_items VALUES ('item1','enc','ins_1','Test Bank','active',NULL,NULL,'cur1','2026-09-08T05:00:00','2026-01-01','2026-09-08')")
    o.execute("INSERT INTO plaid_items VALUES ('item2','enc2','ins_2','Old Bank','removed',NULL,NULL,NULL,NULL,'2026-01-01','2026-01-03')")
    o.execute("INSERT INTO plaid_accounts VALUES ('pa1','item1','loc1','TOTAL CHECKING',NULL,'depository','checking','1234',1042.8,1000,1,'x')")
    o.execute("INSERT INTO plaid_accounts VALUES ('pa2','item1','loc2','Mortgage',NULL,'loan','mortgage','7364',577164.32,NULL,1,'x')")
    o.execute("INSERT INTO plaid_accounts VALUES ('pa3','item2','loc3','Plaid Checking',NULL,'depository','checking','0000',110,NULL,0,'x')")
    o.execute("INSERT INTO investment_accounts VALUES ('ia1',NULL,'ACME SAVINGS INCENTIVE PLAN-1652','Fidelity','brokerage',0,1,'x','x','fina-1','2026-09-07T05:00:06',470280.92)")
    o.execute("INSERT INTO investment_accounts VALUES ('ia2',NULL,'Cash Management (Joint WROS - TOD)-7733','Fidelity','brokerage',1,1,'x','x','fina-2','2026-09-07T05:00:06',349676.74)")
    o.execute("INSERT INTO investment_accounts VALUES ('ia3',NULL,'Fidelity Rewards Visa Signature Card 6271','Fidelity','credit_card',0,0,'x','x','fina-3','2026-09-07',25712.91)")
    o.execute("INSERT INTO holdings VALUES ('h1','ia1','NTSP500',NULL,'Nt S&P 500 Idx Nl 4',444.658,NULL,NULL,361.08,160560,'Mutual Fund',0,'2026-09-07T05:00:08')")
    o.execute("INSERT INTO crypto_wallets VALUES ('w1','Hot wallet','ethereum','0xabc',1,NULL,'x')")
    o.execute("INSERT INTO crypto_balances VALUES ('b1','w1','ETH',NULL,0.5,1000,'x')")
    o.execute("INSERT INTO defi_positions VALUES ('dp1','w1','Aave V3','aave-v3','Ethereum',300,'x')")
    o.execute("INSERT INTO defi_position_details VALUES ('dd1','dp1','w1','Aave V3','aave-v3','Ethereum','APP_TOKEN','aEthWBTC',0.01,500,50000,'0x1','x')")
    o.execute("INSERT INTO defi_position_details VALUES ('dd2','dp1','w1','Aave V3','aave-v3','Ethereum','BORROWED','variableDebtEthGHO',200,200,1,'0x2','x')")
    o.execute("INSERT INTO bitcoin_wallets VALUES ('bw1','cold','cold',NULL,NULL,2.0,200000,3,'x','x')")
    o.execute("INSERT INTO accounts VALUES ('csv1','Fidelity','Credit Card','Fidelity Credit Card CSV',0,1,0,NULL,NULL,NULL)")
    rows = [
        ("plaid_ptx1", "2026-09-01", "WHOLE FOODS", "Whole Foods", -50.0, "USD", None, "Food & Dining > Groceries", "loc1", "plaid_item1", 0, 0, "ptx1", 0, "FOOD_AND_DRINK_GROCERIES", "plaid"),
        ("plaid_ptx2", "2026-09-02", "WHOLE FOODS", "Whole Foods", -50.0, "USD", None, "Food & Dining > Groceries", "loc1", "plaid_item1", 1, 0, "ptx2", 1, None, "plaid"),  # duplicate → skipped
        ("plaid_ptx3", "2026-09-03", "TRANSFER TO FIDELITY", None, -1000.0, "USD", None, "Transfers > Account Transfer", "loc1", "plaid_item1", 0, 1, "ptx3", 0, None, "plaid"),
        ("fina_x", "2026-09-03", "TRANSFER FROM CHASE", None, 1000.0, "USD", None, "Transfers > Internal Transfer", "ia2", None, 0, 1, None, 0, None, "fina"),
        ("csv_1", "2024-03-01", "COSTCO", "Costco", -200.0, "USD", "Shopping", "Shopping > General Merchandise", "csv1", "file1", 0, 0, None, 0, None, "csv"),
        ("csv_2", "2024-03-02", "MYSTERY", None, -20.0, "USD", None, "Uncategorized > Unknown", "nope", "file1", 0, 0, None, 0, None, "csv"),
    ]
    for r in rows:
        o.execute("INSERT INTO transactions (txn_id, txn_date, description, merchant, amount, currency, category_raw,"
                  " category_normalized, account_id, source_file_id, is_duplicate, is_transfer, plaid_transaction_id,"
                  " pending, personal_finance_category_detailed, source_type) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", r)
    o.execute("INSERT INTO category_overrides VALUES ('ov1','csv_1','Shopping > General Merchandise','Business > Supplies','x','x')")
    o.execute("INSERT INTO budgets VALUES (1,'Food & Dining','Food & Dining',3500,'2026-01-01',NULL,1,0.7,'x','x')")
    o.execute("INSERT INTO category_rules VALUES (1,'whole foods','Food & Dining','Food & Dining > Groceries',0.9,'merchant','x',NULL,12,1)")
    o.execute("INSERT INTO ticker_mappings VALUES ('Nt S&P 500 Idx Nl 4','NTSP500',NULL,'x')")
    o.commit()
    o.close()

    counts = backfill(conn, cfg, str(old_path), as_of="2026-09-08")
    assert counts["connections"] == 2 and counts["plaid_accounts"] == 3 and counts["transactions"] == 5
    assert counts["budgets"] == 1 and counts["category_rules"] == 1 and counts["ticker_mappings"] == 1
    kinds = {r["name"]: (r["kind"], r["is_active"]) for r in conn.execute("SELECT name, kind, is_active FROM accounts")}
    assert kinds["Mortgage"] == ("mortgage", 1) and kinds["Plaid Checking"] == ("checking", 0)
    assert kinds["ACME SAVINGS INCENTIVE PLAN-1652"] == ("retirement_401k", 1)
    assert kinds["Cash Management (Joint WROS - TOD)-7733"] == ("cash_mgmt", 1)
    assert kinds["Fidelity Rewards Visa Signature Card 6271"] == ("credit_card", 0)
    assert kinds["Unknown (legacy import)"] == ("other", 0)
    flows = {r["source_txn_id"]: r["flow"] for r in conn.execute("SELECT source_txn_id, flow FROM transactions_v")}
    assert flows["ptx1"] == "expense" and flows["ptx3"] == "transfer" and flows["fina_x"] == "transfer"
    assert "ptx2" not in flows
    assert conn.execute("SELECT category FROM transactions_v WHERE source_txn_id='csv_1'").fetchone()[0] == "Business > Supplies"
    conn.execute("BEGIN")
    from homeai.ledger.transactions import pair_transfers
    assert pair_transfers(conn) == 1
    from homeai.ledger.snapshots import snapshot_day
    snap = snapshot_day(conn, "2026-09-08")
    conn.execute("COMMIT")
    # assets: checking 1042.8 + 401k positions 160560 + cash mgmt balance 349676.74 + wallet 1300 + btc 200000
    assert round(snap["assets"], 2) == round(1042.8 + 160560 + 349676.74 + 1300 + 200000, 2)
    assert round(snap["liabilities"], 2) == 577164.32
    conn_row = conn.execute("SELECT cursor, status FROM connections WHERE id='item1'").fetchone()
    assert conn_row["cursor"] == "cur1" and conn_row["status"] == "active"
    # re-running is a no-op for transactions
    counts2 = backfill(conn, cfg, str(old_path), as_of="2026-09-08")
    assert counts2["transactions"] == 0 and counts2["transactions_existing"] == 5
