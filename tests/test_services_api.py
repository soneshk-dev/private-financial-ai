from fastapi.testclient import TestClient

from homeai.api.app import create_app
from homeai.ledger.snapshots import snapshot_day
from homeai.services import cashflow, portfolio
from tests.conftest import TODAY, d


def test_monthly_cashflow(conn, seeded):
    rows = cashflow.monthly_cashflow(conn, months=3)
    this = next(r for r in rows if r["month"] == TODAY.strftime("%Y-%m"))
    # income: t2 8000 + b1 12000 + f1 43.29 dividend
    assert round(this["income"], 2) == 20043.29
    # spending: t5 -45.25, t10 +30 refund, b2 -400 (pending target excluded)
    assert round(this["spending"], 2) == -415.25
    assert this["taxes"] == -1500 and this["loan_payments"] == -2200
    assert round(this["investing"], 2) == -10043.29          # f2 reinvest + f3 purchase
    assert this["transfers"] == -300                          # t6/t7 cancel out, t11 unpaired
    personal = next(r for r in cashflow.monthly_cashflow(conn, months=3, entity="personal") if r["month"] == this["month"])
    assert round(personal["income"], 2) == 8043.29


def test_spending_by_category(conn, seeded):
    out = cashflow.spending_by_category(conn, TODAY.strftime("%Y-%m"))
    l1 = {r["category"]: r["spent"] for r in out["by_level1"]}
    # Shopping = Adobe 400 (GENERAL_SERVICES → Shopping) less the 30 Amazon refund
    assert l1["Food & Dining"] == 45.25 and l1["Shopping"] == 370.0
    assert out["total"] == 415.25
    assert out["top_merchants"][0]["merchant"] == "Adobe"


def test_budget_status(conn, seeded):
    conn.execute("INSERT INTO budgets (category_l1, monthly_limit, effective_from, alert_threshold) VALUES"
                 " ('Food & Dining', 50, '2026-01-01', 0.8)")
    conn.execute("INSERT INTO budgets (category_l1, monthly_limit, effective_from) VALUES ('Restaurants', 100, '2026-01-01')")
    conn.execute("INSERT INTO budgets (category_l1, monthly_limit, effective_from) VALUES ('Taxes', 2000, '2026-01-01')")
    st = {b["category"]: b for b in cashflow.budget_status(conn, TODAY.strftime("%Y-%m"))}
    assert st["Food & Dining"]["spent"] == 45.25 and st["Food & Dining"]["status"] == "warning"
    assert st["Restaurants"]["spent"] == 45.25 and st["Restaurants"]["status"] == "ok"
    assert st["Taxes"]["spent"] == 1500.0 and st["Taxes"]["status"] == "ok"


def test_search_transactions(conn, seeded):
    rows = cashflow.search_transactions(conn, flow="expense", include_pending=False)
    assert {r["source_txn_id"] for r in rows} == {"t3", "t4", "t5", "b2"}
    assert len(cashflow.search_transactions(conn, q="PAYROLL")) == 2
    assert len(cashflow.search_transactions(conn, category="Food & Dining", start=d(6))) == 1


def test_positions_and_aave(conn, seeded):
    p = portfolio.positions(conn)
    assert p["total"] == 30000 and p["allocation"]["etf"] == 25000 and p["allocation"]["cash"] == 5000
    from homeai.ledger.balances import replace_defi
    conn.execute("BEGIN")
    replace_defi(conn, seeded["wallet"], TODAY.isoformat(), [
        {"protocol": "Aave V3", "protocol_slug": "aave-v3", "network": "Ethereum", "meta_type": "SUPPLIED",
         "symbol": "aEthWBTC", "quantity": 1.0, "price": 100000, "value": 100000, "contract": "0x1"},
        {"protocol": "Aave V3", "protocol_slug": "aave-v3", "network": "Ethereum", "meta_type": "BORROWED",
         "symbol": "variableDebtEthGHO", "quantity": 40000, "price": 1, "value": 40000, "contract": "0x2"},
    ])
    conn.execute("COMMIT")
    h = portfolio.aave_health(conn)
    assert h["health_factor"] == round(100000 * 0.78 / 40000, 2) and h["status"] == "moderate"
    assert h["liquidation_price_btc"] == round(40000 / 0.78)
    assert h["collateral_breakdown"] == {"WBTC": 100000} and h["debt_breakdown"] == {"GHO": 40000}


def test_api(cfg, conn, seeded):
    conn.execute("BEGIN")
    snapshot_day(conn, TODAY.isoformat())
    conn.execute("COMMIT")
    client = TestClient(create_app(cfg))
    h = client.get("/api/health").json()
    assert h["schema_version"] == 3 and h["counts"]["transactions"] == 17
    accts = client.get("/api/accounts").json()
    assert len(accts) == 6 and any(a["kind"] == "mortgage" for a in accts)
    nw = client.get("/api/net-worth?days=30").json()
    assert nw["net_worth"] == 65000 - 301200 and nw["series"]
    cf = client.get("/api/cashflow?months=2").json()
    assert cf[-1]["month"] == TODAY.strftime("%Y-%m")
    tx = client.get("/api/transactions", params={"flow": "tax"}).json()
    assert len(tx) == 1 and tx[0]["description"] == "IRS USATAXPYMT"
    r = client.patch(f"/api/transactions/{tx[0]['id']}", json={"flow_type": "expense"})
    assert r.status_code == 200
    assert client.get("/api/transactions", params={"flow": "tax"}).json() == []
    r = client.patch(f"/api/accounts/{seeded['chk']}", json={"entity": "business:acme"})
    assert r.status_code == 200
    assert client.get("/api/positions").json()["total"] == 30000
    assert client.get("/link").status_code == 200
