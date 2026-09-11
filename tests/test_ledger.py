from datetime import date

from homeai.db import migrate
from homeai.ledger import classify as c
from homeai.ledger.accounts import kind_from_name, kind_from_plaid, list_accounts, set_locked, upsert_account
from homeai.ledger.snapshots import snapshot_day, series
from homeai.ledger.transactions import (pair_transfers, reclassify_all, remove_transaction, set_override,
                                        txn_id, upsert_transaction)
from tests.conftest import TODAY, d


def test_migrate_is_idempotent(conn):
    assert migrate(conn) == []
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"accounts", "transactions", "balances_daily", "positions", "snapshots_daily", "connections"} <= tables


# ---------------------------------------------------------------- classify
def test_normalize_category_sources():
    assert c.normalize_category("FOOD_AND_DRINK > FOOD_AND_DRINK_RESTAURANT", "plaid") == "Food & Dining > Restaurants"
    assert c.normalize_category("TRANSFER_OUT > TRANSFER_OUT_ACCOUNT_TRANSFER") == "Transfers > Account Transfer"
    assert c.normalize_category("GENERAL_MERCHANDISE > GENERAL_MERCHANDISE_SOMETHING_NEW", "plaid") == "Shopping > Something New"
    assert c.normalize_category("buy & trade", "fina") == "Financial Services > Investment Trades"
    assert c.normalize_category("restaurants & other") == "Food & Dining > Restaurants"
    assert c.normalize_category("Food & Dining > fast food") == "Food & Dining > Fast Food"
    assert c.normalize_category("grocery stores") == "Food & Dining"
    assert c.normalize_category(None) == "Uncategorized"


def test_infer_flow_rules():
    f = c.infer_flow
    assert f("Income > Salary & Wages", 8000, "checking", "ACME PAYROLL") == "income"
    assert f("Transfers > Credit Card Payment", -2500, "checking", "ONLINE PAYMENT TO CARD") == "transfer"
    assert f("Financial Services > Credit Card Payment", -2500, "checking", "PAYMENT") == "transfer"
    assert f("Uncategorized", 2500, "credit_card", "PAYMENT THANK YOU") == "transfer"
    assert f("Income > Other Income", 12843, "credit_card", "AUTOMATIC PAYMENT - THANK") == "transfer"
    assert f("Income > Other Income", 14130, "credit_card", "PAYMENT MADE BY ACCOUNT ENDING I") == "transfer"
    assert f("Financial Services > Mortgage Payment", -2200, "checking", "MORTGAGE") == "loan_payment"
    assert f("Uncategorized", -2200, "mortgage", "PAYMENT") == "loan_payment"
    assert f("Financial Services > Tax Payment", -1500, "checking", "IRS USATAXPYMT") == "tax"
    assert f("Transfers > Internal Transfer", -43.29, "brokerage", "REINVESTMENT FIDELITY MMKT") == "investment_buy"
    assert f("Income > Other Income", 43.29, "brokerage", "DIVIDEND RECEIVED") == "dividend"
    assert f("Financial Services > Investment Trades", -10000, "brokerage", "YOU BOUGHT VTI") == "investment_buy"
    assert f("Financial Services > Investment Sales", 5000, "brokerage", "YOU SOLD VTI") == "investment_sell"
    assert f("Shopping > Online Shopping", 30, "credit_card", "AMAZON REFUND") == "refund"
    assert f("Food & Dining > Groceries", -120.5, "credit_card", "WHOLE FOODS") == "expense"
    assert f("Income > Interest Earned", 1.23, "savings", "INTEREST PAID") == "interest"
    assert f("Financial Services > Interest Charges", -12, "credit_card", "INTEREST CHARGE") == "fee"
    assert f("Uncategorized", 500, "checking", "MOBILE DEPOSIT") == "unknown"
    assert f("Financial Services > Loans & Fees", -50000, "checking", "HELOC PAYMENT") == "loan_payment"
    assert f("Home & Housing > Home", -2792, "cash_mgmt", "BILL PAYMENT HUNTINGTON MORTGAGE (Cash)") == "loan_payment"
    assert f("Income > Other Income", 1200, "checking", "MORTGAGE ESCROW REFUND") == "income"


def test_user_rules_take_precedence():
    from homeai.config import FlowRule
    rules = c.compile_rules([FlowRule(pattern=r"HODL VENTURES", flow_type="transfer")])
    assert c.infer_flow("Utilities > Rent", -1000, "checking", "HODL VENTURES IN", rules) == "transfer"


def test_kind_detection(cfg):
    assert kind_from_name("ACME SAVINGS INCENTIVE PLAN-1652") == "retirement_401k"
    assert kind_from_name("BrokerageLink Roth-2800") == "roth_401k"
    assert kind_from_name("Rollover IRA-5040") == "ira"
    assert kind_from_name("Health Savings Account-2557") == "hsa"
    assert kind_from_name("Cash Management (Joint WROS - TOD)-7733") == "cash_mgmt"
    assert kind_from_name("ACME LLC DEFERRED COMPENSATION PLAN-2512") == "deferred_comp"
    assert kind_from_name("INDIVIDUAL - YOUTH ACCOUNT-9307") == "custodial"
    assert kind_from_name("Individual - TOD-1439") == "brokerage"
    assert kind_from_plaid("loan", "mortgage", "Mortgage 7364", "Big Bank", cfg) == "mortgage"
    assert kind_from_plaid("loan", "mortgage", "Mortgage", "Test Credit Union", cfg) == "heloc"
    assert kind_from_plaid("credit", "credit card", "CREDIT CARD", "Chase", cfg) == "credit_card"
    assert kind_from_plaid("investment", "crypto exchange", "Total Balance", "Kraken", cfg) == "crypto_exchange"
    assert kind_from_plaid("depository", "checking", "TOTAL CHECKING", "Chase", cfg) == "checking"


# ---------------------------------------------------------------- accounts
def test_account_upsert_and_lock(conn):
    conn.execute("BEGIN")
    aid = upsert_account(conn, source="plaid", source_account_id="x", name="Old Name", kind="checking", institution="B")
    assert upsert_account(conn, source="plaid", source_account_id="x", name="New Name", kind="savings") == aid
    row = conn.execute("SELECT name, kind FROM accounts WHERE id=?", (aid,)).fetchone()
    assert (row["name"], row["kind"]) == ("New Name", "savings")
    set_locked(conn, aid, kind="money_market", entity="business:acme")
    upsert_account(conn, source="plaid", source_account_id="x", name="Third", kind="checking")
    row = conn.execute("SELECT name, kind, entity, is_liability FROM accounts WHERE id=?", (aid,)).fetchone()
    assert (row["name"], row["kind"], row["entity"], row["is_liability"]) == ("Third", "money_market", "business:acme", 0)
    set_locked(conn, aid, kind="heloc")
    assert conn.execute("SELECT is_liability FROM accounts WHERE id=?", (aid,)).fetchone()[0] == 1
    conn.execute("COMMIT")


# ---------------------------------------------------------------- transactions
def test_upsert_idempotent_and_flow(conn, seeded):
    n = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    conn.execute("BEGIN")
    tid, status = upsert_transaction(conn, source="plaid", source_txn_id="t3", account_id=seeded["card"],
                                     posted_at=d(35), amount=-120.5, description="WHOLE FOODS", merchant="Whole Foods",
                                     category_raw="FOOD_AND_DRINK > FOOD_AND_DRINK_GROCERIES")
    conn.execute("COMMIT")
    assert status == "updated" and tid == txn_id("plaid", "t3")
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == n
    flows = {r["source_txn_id"]: r["flow"] for r in conn.execute("SELECT source_txn_id, flow FROM transactions_v")}
    assert flows["t1"] == "income" and flows["t3"] == "expense" and flows["t6"] == "transfer"
    assert flows["t7"] == "transfer" and flows["t8"] == "loan_payment" and flows["t9"] == "tax"
    assert flows["f1"] == "dividend" and flows["f2"] == "investment_buy" and flows["f3"] == "investment_buy"
    assert flows["t10"] == "refund" and flows["t11"] == "transfer"


def test_pending_to_posted_keeps_override(conn, seeded):
    conn.execute("BEGIN")
    pend_id = txn_id("plaid", "pend1")
    set_override(conn, pend_id, category="Home & Housing > Furniture")
    tid, status = upsert_transaction(conn, source="plaid", source_txn_id="post1", account_id=seeded["card"],
                                     posted_at=d(0), amount=-80.0, description="TARGET", merchant="Target",
                                     category_raw="GENERAL_MERCHANDISE > GENERAL_MERCHANDISE_SUPERSTORES",
                                     pending=False, replaces_source_txn_id="pend1")
    conn.execute("COMMIT")
    assert status == "replaced"
    assert conn.execute("SELECT COUNT(*) FROM transactions WHERE source_txn_id IN ('pend1','post1')").fetchone()[0] == 1
    row = conn.execute("SELECT * FROM transactions_v WHERE id=?", (tid,)).fetchone()
    assert row["pending"] == 0 and row["category"] == "Home & Housing > Furniture" and row["source_txn_id"] == "post1"
    conn.execute("BEGIN")
    assert remove_transaction(conn, "plaid", "post1")
    conn.execute("COMMIT")


def test_pair_transfers(conn, seeded):
    conn.execute("BEGIN")
    pairs = pair_transfers(conn)
    conn.execute("COMMIT")
    assert pairs == 1
    g = {r["source_txn_id"]: r["transfer_group"] for r in conn.execute(
        "SELECT source_txn_id, transfer_group FROM transactions WHERE source_txn_id IN ('t6','t7')")}
    assert g["t6"] and g["t6"] == g["t7"]
    # t11 (transfer to savings) has no counterpart in the ledger → stays unpaired
    assert conn.execute("SELECT transfer_group FROM transactions WHERE source_txn_id='t11'").fetchone()[0] is None


def test_reclassify_keeps_overrides(conn, seeded):
    conn.execute("BEGIN")
    set_override(conn, txn_id("plaid", "t5"), flow_type="transfer")
    reclassify_all(conn)
    conn.execute("COMMIT")
    row = conn.execute("SELECT flow_type, flow_type_override FROM transactions WHERE source_txn_id='t5'").fetchone()
    assert (row["flow_type"], row["flow_type_override"]) == ("expense", "transfer")
    assert conn.execute("SELECT flow FROM transactions_v WHERE source_txn_id='t5'").fetchone()[0] == "transfer"


# ---------------------------------------------------------------- snapshots
def test_snapshot_math(conn, seeded):
    conn.execute("BEGIN")
    snap = snapshot_day(conn, TODAY.isoformat())
    conn.execute("COMMIT")
    # assets: chk 5000 + brok positions 30000 + wallet 10000 + biz 20000 = 65000; liabilities: card 1200 + mort 300000
    assert snap["assets"] == 65000 and snap["liabilities"] == 301200 and snap["net_worth"] == 65000 - 301200
    assert snap["by_class"]["investments"] == 30000 and snap["by_class"]["liability"] == -301200
    assert round(snap["by_entity"]["business:acme"]) == 20000
    assert series(conn, 30)[-1]["net_worth"] == snap["net_worth"]
    accounts = {a["name"]: a for a in list_accounts(conn)}
    assert accounts["Mortgage"]["latest_balance"] == 300000 and accounts["Mortgage"]["asset_class"] == "liability"
