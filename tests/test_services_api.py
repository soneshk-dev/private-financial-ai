import pytest
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


def test_categories_taxonomy_and_recategorize(conn, seeded):
    from homeai.services import categories as C
    from homeai.ledger.transactions import upsert_transaction
    tax = C.taxonomy(conn)
    food = next(t for t in tax if t["level1"] == "Food & Dining")
    assert any(s["category"] == "Food & Dining > Groceries" for s in food["subs"])
    amazon = conn.execute("SELECT id FROM transactions_v WHERE merchant = 'Amazon' LIMIT 1").fetchone()["id"]
    with pytest.raises(ValueError):                       # unknown level 1
        C.validate_category(conn, "Gadgets > Toys")
    with pytest.raises(ValueError):                       # unknown sub without allow_new
        C.validate_category(conn, "Shopping > Gadgets")
    assert C.validate_category(conn, "shopping > gadgets", allow_new=True) == "Shopping > Gadgets"
    sim = C.similar(conn, amazon)
    r = C.recategorize(conn, amazon, "Shopping > Electronics", scope="merchant", remember=True)
    assert r["affected"] == sim["n"] + 1 and r["rule_id"]
    cats = {x["category"] for x in conn.execute("SELECT category FROM transactions_v WHERE merchant = 'Amazon'")}
    assert cats == {"Shopping > Electronics"}
    assert C.similar(conn, amazon)["rule"]["category"] == "Shopping > Electronics"
    conn.execute("BEGIN")                                 # a freshly synced Amazon row picks the rule up
    upsert_transaction(conn, source="plaid", source_txn_id="amz-new", account_id=seeded["card"], posted_at="2026-09-27",
                       amount=-12.5, description="AMAZON MKTPLACE", merchant="Amazon",
                       category_raw="GENERAL_MERCHANDISE > GENERAL_MERCHANDISE_ONLINE_MARKETPLACES")
    conn.execute("COMMIT")
    assert conn.execute("SELECT category FROM transactions_v WHERE source_txn_id = 'amz-new'").fetchone()[0] == "Shopping > Electronics"
    out = C.rename_category(conn, "Shopping > Electronics", "Shopping > Online Shopping")
    assert out["affected"] >= 2 and out["rules"] == 1
    assert conn.execute("SELECT COUNT(*) FROM transactions_v WHERE category = 'Shopping > Electronics'").fetchone()[0] == 0
    assert C.delete_rule(conn, r["rule_id"]) and not C.list_rules(conn)


def test_categories_api(cfg, conn, seeded):
    from fastapi.testclient import TestClient
    from homeai.api.app import create_app
    client = TestClient(create_app(cfg))
    tax = client.get("/api/categories").json()
    assert [t["level1"] for t in tax["taxonomy"]][0] == "Food & Dining"
    tid = client.get("/api/transactions", params={"q": "TARGET"}).json()[0]["id"]
    assert client.post(f"/api/transactions/{tid}/category", json={"category": "Nope > X"}).status_code == 400
    r = client.post(f"/api/transactions/{tid}/category", json={"category": "Shopping > Superstores", "scope": "merchant", "remember": True})
    assert r.status_code == 200 and r.json()["rule_id"]
    assert client.get(f"/api/transactions/{tid}/similar").json()["rule"]["category"] == "Shopping > Superstores"
    assert client.patch(f"/api/transactions/{tid}", json={"category": "Made Up"}).status_code == 400
    assert client.post("/api/categories/rename", json={"from_category": "Shopping > Superstores", "to_category": "Shopping > Department Stores"}).json()["affected"] >= 1
    assert client.delete(f"/api/categories/rules/{r.json()['rule_id']}").json()["ok"]


def test_categories_core_keep_and_suggestions(conn, seeded):
    from homeai.services import categories as C
    from homeai.ledger.transactions import set_override
    tid = conn.execute("SELECT id FROM transactions_v WHERE merchant = 'Amazon' LIMIT 1").fetchone()["id"]
    conn.execute("BEGIN"); set_override(conn, tid, category="Food & Dining > Grocery Shopping"); conn.execute("COMMIT")
    tax = {t["level1"]: t for t in C.taxonomy(conn)}
    stray = [s for s in tax["Food & Dining"]["subs"] if not s["core"]]
    assert [s["name"] for s in stray] == ["Grocery Shopping"] and tax["Food & Dining"]["stray"] == 1
    sug = C.suggest_merges(conn)
    assert sug and sug[0]["from"] == "Food & Dining > Grocery Shopping" and sug[0]["to"] == "Food & Dining > Groceries"
    C.set_kept(conn, "Food & Dining > Grocery Shopping", True)        # promote it instead
    assert "Food & Dining > Grocery Shopping" in C.core_categories(conn) and not C.suggest_merges(conn)
    C.set_kept(conn, "Food & Dining > Grocery Shopping", False)
    assert C.suggest_merges(conn)
    assert C.rule_counts(conn) == {}
