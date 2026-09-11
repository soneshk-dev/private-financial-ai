-- Phase E: entities, per-transaction entity override, goals, alert dedupe.

ALTER TABLE transactions ADD COLUMN entity_override TEXT;

DROP VIEW transactions_v;
CREATE VIEW transactions_v AS
SELECT t.id, t.source, t.source_txn_id, t.account_id, a.name AS account_name, a.kind AS account_kind,
       a.institution, t.posted_at, t.authorized_at, t.amount, t.currency, t.description, t.merchant,
       t.category_raw,
       COALESCE(t.category_override, t.category) AS category,
       COALESCE(t.flow_type_override, t.flow_type) AS flow,
       COALESCE(t.entity_override, t.entity) AS entity,
       t.pending, t.transfer_group, t.meta, t.created_at, t.updated_at,
       substr(COALESCE(t.category_override, t.category), 1,
              CASE WHEN instr(COALESCE(t.category_override, t.category), ' > ') > 0
                   THEN instr(COALESCE(t.category_override, t.category), ' > ') - 1
                   ELSE length(COALESCE(t.category_override, t.category)) END) AS category_l1
FROM transactions t JOIN accounts a ON a.id = t.account_id;

CREATE TABLE entities (
    slug        TEXT PRIMARY KEY,            -- 'personal' or 'business:<name>'
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'business',   -- business | personal | trust
    tax_form    TEXT,                        -- s_corp | llc | sole_prop | ...
    notes       TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    updated_at  TEXT NOT NULL
);
INSERT INTO entities (slug, name, kind, updated_at) VALUES ('personal', 'Personal', 'personal', '2026-01-01T00:00:00+00:00');

CREATE TABLE goals (
    slug                 TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    kind                 TEXT NOT NULL,      -- save | debt | reserve | purchase | retirement
    target_amount        REAL,
    target_date          TEXT,
    start_amount         REAL,               -- debt goals: balance when the goal was set
    current_amount       REAL,               -- manual current value (used when no linked accounts)
    linked_account_ids   TEXT,               -- JSON list
    monthly_contribution REAL,
    priority             INTEGER NOT NULL DEFAULT 2,
    notes                TEXT,
    updated_at           TEXT NOT NULL
);

CREATE TABLE alerts_sent (
    key       TEXT PRIMARY KEY,              -- alert id + day
    sent_at   TEXT NOT NULL,
    payload   TEXT
);
