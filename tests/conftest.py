import os
from datetime import date, timedelta

import pytest

from homeai.config import Config
from homeai.db import connect, migrate
from homeai.ledger.accounts import upsert_account
from homeai.ledger.balances import record_balance, replace_positions
from homeai.ledger.transactions import upsert_transaction

TODAY = date(2026, 9, 28)   # late in the month so d(0..27) all land in the same month


@pytest.fixture
def cfg(tmp_path):
    priv = tmp_path / "private"
    vault = tmp_path / "vault"
    priv.mkdir()
    vault.mkdir()
    os.environ["HOMEAI_PRIVATE_DIR"] = str(priv)
    os.environ["HOMEAI_VAULT_DIR"] = str(vault)
    return Config(private_dir=priv, vault_dir=vault, secrets_dir=tmp_path / "secrets",
                  heloc_institutions=["Test Credit Union"])


@pytest.fixture
def conn(cfg):
    c = connect(cfg.db_path)
    migrate(c)
    yield c
    c.close()


def d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


@pytest.fixture
def seeded(conn):
    """A small synthetic household: checking, card, brokerage, mortgage, wallet."""
    conn.execute("BEGIN")
    chk = upsert_account(conn, source="plaid", source_account_id="chk1", name="Everyday Checking", kind="checking",
                         institution="Test Bank", mask="1111", connection_id="item1")
    card = upsert_account(conn, source="plaid", source_account_id="cc1", name="Rewards Card", kind="credit_card",
                          institution="Test Bank", mask="2222", connection_id="item1")
    brok = upsert_account(conn, source="fina", source_account_id="fina-brok", name="Individual Brokerage",
                          kind="brokerage", institution="Fidelity")
    mort = upsert_account(conn, source="plaid", source_account_id="mort1", name="Mortgage", kind="mortgage",
                          institution="Test Bank", connection_id="item1")
    wallet = upsert_account(conn, source="zerion", source_account_id="ethereum:0xabc", name="Hot wallet",
                            kind="crypto_wallet", institution="Ethereum", meta={"chain": "ethereum", "address": "0xabc"})
    biz = upsert_account(conn, source="plaid", source_account_id="bizchk", name="Business Checking", kind="checking",
                         institution="Test Bank", entity="business:acme", connection_id="item2")

    record_balance(conn, chk, TODAY.isoformat(), 5000, 4800, "plaid")
    record_balance(conn, card, TODAY.isoformat(), 1200, None, "plaid")
    record_balance(conn, mort, TODAY.isoformat(), 300000, None, "plaid")
    record_balance(conn, wallet, TODAY.isoformat(), 10000, None, "zerion")
    record_balance(conn, biz, TODAY.isoformat(), 20000, None, "plaid")
    replace_positions(conn, brok, TODAY.isoformat(), [
        {"symbol": "VTI", "description": "Vanguard Total Market ETF", "quantity": 100, "price": 250, "value": 25000,
         "cost_basis": 20000, "asset_class": "etf"},
        {"symbol": None, "description": "Fidelity Government Money Market", "quantity": 5000, "price": 1,
         "value": 5000, "asset_class": "cash"},
    ], "fina")

    tx = [
        # (source, id, account, days_ago, amount, desc, merchant, category_raw)
        ("plaid", "t1", chk, 40, 8000.00, "ACME CORP PAYROLL", "Acme Corp", "INCOME > INCOME_WAGES"),
        ("plaid", "t2", chk, 10, 8000.00, "ACME CORP PAYROLL", "Acme Corp", "INCOME > INCOME_WAGES"),
        ("plaid", "t3", card, 35, -120.50, "WHOLE FOODS", "Whole Foods", "FOOD_AND_DRINK > FOOD_AND_DRINK_GROCERIES"),
        ("plaid", "t4", card, 30, -60.00, "SHELL OIL", "Shell", "TRANSPORTATION > TRANSPORTATION_GAS"),
        ("plaid", "t5", card, 5, -45.25, "CHIPOTLE", "Chipotle", "FOOD_AND_DRINK > FOOD_AND_DRINK_RESTAURANT"),
        ("plaid", "t6", chk, 20, -2500.00, "ONLINE PAYMENT TO CARD", "Test Bank", "LOAN_PAYMENTS > LOAN_PAYMENTS_CREDIT_CARD_PAYMENT"),
        ("plaid", "t7", card, 19, 2500.00, "PAYMENT THANK YOU", None, "TRANSFER_IN > TRANSFER_IN_ACCOUNT_TRANSFER"),
        ("plaid", "t8", chk, 15, -2200.00, "MORTGAGE PAYMENT", "Test Bank", "LOAN_PAYMENTS > LOAN_PAYMENTS_MORTGAGE_PAYMENT"),
        ("plaid", "t9", chk, 12, -1500.00, "IRS USATAXPYMT", "IRS", "GOVERNMENT_AND_NON_PROFIT > GOVERNMENT_AND_NON_PROFIT_TAX_PAYMENT"),
        ("fina", "f1", brok, 8, 43.29, "DIVIDEND RECEIVED FIDELITY GOVERNMENT MONEY MARKET", None, "other income"),
        ("fina", "f2", brok, 8, -43.29, "REINVESTMENT FIDELITY GOVERNMENT MONEY MARKET", None, "transfer"),
        ("fina", "f3", brok, 25, -10000.00, "YOU BOUGHT VANGUARD TOTAL MARKET ETF", None, "buy & trade"),
        ("plaid", "t10", card, 3, 30.00, "AMAZON REFUND", "Amazon", "GENERAL_MERCHANDISE > GENERAL_MERCHANDISE_ONLINE_MARKETPLACES"),
        ("plaid", "t11", chk, 2, -300.00, "TRANSFER TO SAVINGS", None, "TRANSFER_OUT > TRANSFER_OUT_SAVINGS"),
        ("plaid", "b1", biz, 9, 12000.00, "CLIENT PAYMENT", "Client Co", "INCOME > INCOME_OTHER_INCOME"),
        ("plaid", "b2", biz, 7, -400.00, "ADOBE", "Adobe", "GENERAL_SERVICES > GENERAL_SERVICES_OTHER_GENERAL_SERVICES"),
    ]
    for src, sid, acct, ago, amt, desc, merch, raw in tx:
        upsert_transaction(conn, source=src, source_txn_id=sid, account_id=acct, posted_at=d(ago), amount=amt,
                           description=desc, merchant=merch, category_raw=raw)
    # a pending card transaction
    upsert_transaction(conn, source="plaid", source_txn_id="pend1", account_id=card, posted_at=d(1), amount=-80.0,
                       description="TARGET", merchant="Target", category_raw="GENERAL_MERCHANDISE > GENERAL_MERCHANDISE_SUPERSTORES",
                       pending=True)
    conn.execute("COMMIT")
    return {"chk": chk, "card": card, "brok": brok, "mort": mort, "wallet": wallet, "biz": biz}
