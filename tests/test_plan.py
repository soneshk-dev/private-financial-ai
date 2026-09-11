from datetime import date

from homeai.config import EntityDef, EntityRule, GoalDef, IncomeDef
from homeai.services import alerts, business, goals, runway, taxes
from homeai.services.taxes import federal_tax
from homeai.ledger.transactions import txn_id
from tests.conftest import TODAY, d


def test_entities_rules_and_pnl(cfg, conn, seeded):
    cfg.entities = [EntityDef(slug="business:acme", name="Acme LLC", tax_form="s_corp")]
    cfg.entity_rules = [EntityRule(pattern=r"ADOBE", entity="business:acme")]
    conn.execute("BEGIN")
    assert business.sync_entities(conn, cfg) == 1
    n = business.apply_entity_rules(conn, cfg)
    conn.execute("COMMIT")
    assert n == 1  # ADOBE (already on the business account) now carries an explicit override
    ents = {e["slug"]: e for e in business.list_entities(conn)}
    assert ents["business:acme"]["accounts"] == 1 and ents["personal"]["kind"] == "personal"
    rows = business.pnl(conn, "business:acme", 3)
    this = next(r for r in rows if r["month"] == TODAY.strftime("%Y-%m"))
    assert this["revenue"] == 12000 and this["expenses"] == -400 and this["net"] == 11600
    s = {x["slug"]: x for x in business.summary(conn, 3)}
    assert s["business:acme"]["net"] == 11600 and s["personal"]["revenue"] > 0
    # entity override through the shared setter, visible in the view
    from homeai.ledger.transactions import set_override
    conn.execute("BEGIN")
    set_override(conn, txn_id("plaid", "t5"), entity="business:acme")
    conn.execute("COMMIT")
    assert conn.execute("SELECT entity FROM transactions_v WHERE source_txn_id='t5'").fetchone()[0] == "business:acme"


def test_review_queue_flags_business_looking_rows(cfg, conn, seeded):
    conn.execute("BEGIN")
    from homeai.ledger.transactions import upsert_transaction
    upsert_transaction(conn, source="plaid", source_txn_id="rq1", account_id=seeded["card"], posted_at=d(4), amount=-1200,
                       description="FIGMA SOFTWARE", merchant="Figma", category_raw="GENERAL_SERVICES > GENERAL_SERVICES_OTHER_GENERAL_SERVICES")
    upsert_transaction(conn, source="plaid", source_txn_id="rq2", account_id=seeded["chk"], posted_at=d(3), amount=-9000,
                       description="WIRE TO ACME LLC", category_raw="TRANSFER_OUT > TRANSFER_OUT_OTHER_TRANSFER_OUT")
    conn.execute("COMMIT")
    q = {r["description"]: r["reason"] for r in business.review_queue(conn, months=12, min_amount=250)}
    assert q["FIGMA SOFTWARE"] == "business-looking merchant or category"
    assert q["WIRE TO ACME LLC"] in ("business-looking merchant or category", "large unpaired transfer")
    assert "WHOLE FOODS" not in q


def test_runway_projection(cfg, conn, seeded):
    cfg.runway.incomes = [IncomeDef(name="Salary", match="PAYROLL", until="2026-11-30"),
                          IncomeDef(name="Board", match="BOARD", monthly=1000)]
    cfg.runway.burn_months = 2
    r = runway.project(conn, cfg, today=TODAY)
    assert r["reserve"] == 5000                      # personal cash: checking only (business checking excluded)
    sal = next(i for i in r["incomes"] if i["name"] == "Salary")
    assert sal["matches"] == 2 and sal["monthly"] == round(16000 / 3, 2)
    assert r["series"][0]["month"] == "2026-09" and len(r["series"]) == cfg.runway.horizon_months + 1
    dec = next(s for s in r["series"] if s["month"] == "2026-12")
    assert dec["income"] == 1000                     # salary ended in November
    assert r["burn"]["months_averaged"] >= 1 and r["burn"]["total"] > 0 and "median" in r["burn"]["method"]
    assert r["months_no_income"] == round(5000 / r["burn"]["total"], 1)


def test_federal_brackets_and_estimate(cfg, conn, seeded):
    tax, marginal, detail = federal_tax(150000, cfg.tax.brackets)
    assert marginal == 0.22 and round(tax) == round(24800 * 0.10 + 76000 * 0.12 + 49200 * 0.22)
    cfg.tax.prior_year_total_tax = 20000
    cfg.tax.prior_year_agi = 200000
    cfg.tax.additional_income = {"capital_gains": 5000, "k1": 200000}   # enough income to leave tax due
    e = taxes.estimate(conn, cfg, today=TODAY)
    assert e["income"]["wages"] == 16000 and e["income"]["wages_source"].startswith("net deposits")
    assert e["income"]["investment_income"] == 43.29
    assert e["federal"]["paid"] == 1500 and e["state"]["paid"] == 0
    assert e["safe_harbor"]["required_payments"] == 22000 and e["safe_harbor"]["met"] is False
    assert e["schedule"] and e["schedule"][0]["due"] == "2027-01-15"   # after Sep 15 on TODAY=Sep 28
    assert e["income"]["agi"] == 16000 + 43.29 + 205000   # business income is not personal AGI here (no entity synced)
    assert e["federal"]["marginal_rate"] == 0.22 and e["roth_headroom_in_bracket"] == round(211400 - e["taxable_income"], 2)
    assert e["federal"]["remaining"] > 0 and e["schedule"][0]["federal"] == e["federal"]["remaining"]


def test_goals_progress(cfg, conn, seeded):
    cfg.goals = [GoalDef(slug="college", name="College", kind="save", target_amount=30000, target_date="2028-08-01",
                         linked_accounts=["Individual Brokerage"], monthly_contribution=100),
                 GoalDef(slug="mortgage", name="Pay down mortgage", kind="debt", start_amount=400000, linked_accounts=["Mortgage"])]
    conn.execute("BEGIN")
    assert goals.sync_goals(conn, cfg) == 2
    conn.execute("COMMIT")
    p = {g["slug"]: g for g in goals.progress(conn, today=TODAY)}
    assert p["college"]["current"] == 30000 and p["college"]["pct"] == 1.0 and p["college"]["remaining"] == 0
    assert p["mortgage"]["current"] == 300000 and p["mortgage"]["pct"] == 0.25


def test_alerts_evaluate(cfg, conn, seeded):
    conn.execute("INSERT INTO budgets (category_l1, monthly_limit, effective_from) VALUES ('Food & Dining', 10, '2026-01-01')")
    found = {a["key"]: a["text"] for a in alerts.evaluate(conn, cfg, today=TODAY)}
    assert "budget_Food & Dining" in found
    assert not any(k.startswith("large_") for k in found)   # nothing over $5,000 yesterday
    # dedupe: nothing configured for telegram → not sent, nothing recorded
    res = alerts.send_new(conn, cfg, list(alerts.evaluate(conn, cfg, today=TODAY)), today=TODAY)
    assert res["sent"] == 0 and conn.execute("SELECT COUNT(*) FROM alerts_sent").fetchone()[0] == 0
