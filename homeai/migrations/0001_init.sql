-- homeai ledger schema v1
-- Conventions: dates are ISO 'YYYY-MM-DD'; timestamps are ISO-8601 UTC;
-- money is REAL in the account's currency; amounts are SIGNED (negative = money out).

CREATE TABLE accounts (
    id                 TEXT PRIMARY KEY,                 -- acc_<sha1(source:source_account_id)[:16]>
    source             TEXT NOT NULL,                    -- plaid | fina | zerion | bitcoin | csv | manual
    source_account_id  TEXT NOT NULL,
    name               TEXT NOT NULL,
    institution        TEXT,
    kind               TEXT NOT NULL,                    -- see homeai.config.AccountKind
    is_liability       INTEGER NOT NULL DEFAULT 0,
    entity             TEXT NOT NULL DEFAULT 'personal', -- personal | business:<slug>
    currency           TEXT NOT NULL DEFAULT 'USD',
    mask               TEXT,
    is_active          INTEGER NOT NULL DEFAULT 1,
    connection_id      TEXT,                             -- e.g. plaid item id
    meta               TEXT,                             -- JSON
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    UNIQUE (source, source_account_id)
);
CREATE INDEX idx_accounts_active ON accounts(is_active, kind);

CREATE TABLE balances_daily (
    account_id   TEXT NOT NULL REFERENCES accounts(id),
    as_of        TEXT NOT NULL,
    balance      REAL NOT NULL,                          -- liabilities stored POSITIVE (amount owed)
    available    REAL,
    source       TEXT NOT NULL,
    captured_at  TEXT NOT NULL,
    PRIMARY KEY (account_id, as_of)
);

CREATE TABLE transactions (
    id                 TEXT PRIMARY KEY,                 -- txn_<sha1(source:source_txn_id)[:20]>
    source             TEXT NOT NULL,
    source_txn_id      TEXT NOT NULL,
    account_id         TEXT NOT NULL REFERENCES accounts(id),
    posted_at          TEXT NOT NULL,
    authorized_at      TEXT,
    amount             REAL NOT NULL,
    currency           TEXT NOT NULL DEFAULT 'USD',
    description        TEXT,
    merchant           TEXT,
    category_raw       TEXT,
    category           TEXT,                             -- normalized "Level1 > Sub"
    flow_type          TEXT NOT NULL DEFAULT 'unknown',  -- expense|income|transfer|investment_buy|investment_sell|dividend|interest|loan_payment|tax|fee|refund|unknown
    flow_type_override TEXT,
    category_override  TEXT,
    entity             TEXT NOT NULL DEFAULT 'personal',
    pending            INTEGER NOT NULL DEFAULT 0,
    transfer_group     TEXT,
    meta               TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    UNIQUE (source, source_txn_id)
);
CREATE INDEX idx_txn_posted ON transactions(posted_at);
CREATE INDEX idx_txn_account ON transactions(account_id, posted_at);
CREATE INDEX idx_txn_flow ON transactions(flow_type, posted_at);
CREATE INDEX idx_txn_category ON transactions(category);

-- Effective view: overrides win. Every read path should use this.
CREATE VIEW transactions_v AS
SELECT t.id, t.source, t.source_txn_id, t.account_id, a.name AS account_name, a.kind AS account_kind,
       a.institution, t.posted_at, t.authorized_at, t.amount, t.currency, t.description, t.merchant,
       t.category_raw,
       COALESCE(t.category_override, t.category) AS category,
       COALESCE(t.flow_type_override, t.flow_type) AS flow,
       t.entity, t.pending, t.transfer_group, t.meta, t.created_at, t.updated_at,
       substr(COALESCE(t.category_override, t.category), 1,
              CASE WHEN instr(COALESCE(t.category_override, t.category), ' > ') > 0
                   THEN instr(COALESCE(t.category_override, t.category), ' > ') - 1
                   ELSE length(COALESCE(t.category_override, t.category)) END) AS category_l1
FROM transactions t JOIN accounts a ON a.id = t.account_id;

CREATE TABLE positions (
    account_id   TEXT NOT NULL REFERENCES accounts(id),
    as_of        TEXT NOT NULL,
    key          TEXT NOT NULL,                          -- symbol, else description
    symbol       TEXT,
    description  TEXT,
    quantity     REAL,
    price        REAL,
    value        REAL NOT NULL,
    cost_basis   REAL,
    asset_class  TEXT,                                   -- cash|equity|etf|fund|bond|crypto|nft|other
    source       TEXT NOT NULL,
    captured_at  TEXT NOT NULL,
    PRIMARY KEY (account_id, as_of, key)
);

CREATE VIEW positions_latest AS
SELECT p.* FROM positions p
JOIN (SELECT account_id, MAX(as_of) AS as_of FROM positions GROUP BY account_id) m
  ON m.account_id = p.account_id AND m.as_of = p.as_of;

CREATE TABLE defi_positions (
    account_id     TEXT NOT NULL REFERENCES accounts(id),
    as_of          TEXT NOT NULL,
    protocol       TEXT NOT NULL,
    protocol_slug  TEXT NOT NULL,
    network        TEXT,
    meta_type      TEXT NOT NULL,                        -- SUPPLIED | BORROWED | CLAIMABLE
    symbol         TEXT NOT NULL,
    quantity       REAL,
    price          REAL,
    value          REAL NOT NULL,                        -- positive magnitude
    contract       TEXT,
    captured_at    TEXT NOT NULL,
    PRIMARY KEY (account_id, as_of, protocol_slug, network, meta_type, symbol, contract)
);

CREATE VIEW defi_positions_latest AS
SELECT d.* FROM defi_positions d
JOIN (SELECT account_id, MAX(as_of) AS as_of FROM defi_positions GROUP BY account_id) m
  ON m.account_id = d.account_id AND m.as_of = d.as_of;

CREATE TABLE snapshots_daily (
    as_of        TEXT PRIMARY KEY,
    assets       REAL NOT NULL,
    liabilities  REAL NOT NULL,
    net_worth    REAL NOT NULL,
    by_class     TEXT NOT NULL,                          -- JSON {class: value}
    by_entity    TEXT NOT NULL,                          -- JSON {entity: net}
    captured_at  TEXT NOT NULL
);

CREATE TABLE connections (
    id             TEXT PRIMARY KEY,                     -- plaid item_id etc.
    connector      TEXT NOT NULL,
    institution    TEXT,
    status         TEXT NOT NULL DEFAULT 'active',       -- active | login_required | error | removed
    secret_enc     TEXT,                                 -- Fernet-encrypted access token
    cursor         TEXT,
    error_code     TEXT,
    error_message  TEXT,
    last_success_at TEXT,
    meta           TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE connector_health (
    connector        TEXT PRIMARY KEY,
    status           TEXT NOT NULL,                      -- ok | error | never
    last_started_at  TEXT,
    last_success_at  TEXT,
    last_error_at    TEXT,
    last_error       TEXT,
    rows_written     INTEGER NOT NULL DEFAULT 0,
    detail           TEXT                                -- JSON
);

CREATE TABLE raw_sync (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    connector   TEXT NOT NULL,
    kind        TEXT NOT NULL,                           -- endpoint / payload type
    ref         TEXT,                                    -- connection or account reference
    fetched_at  TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX idx_raw_sync_fetched ON raw_sync(connector, fetched_at);

CREATE TABLE category_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern     TEXT NOT NULL,                           -- matched against merchant/description
    match_kind  TEXT NOT NULL DEFAULT 'contains',        -- contains | exact | regex
    category    TEXT NOT NULL,
    flow_type   TEXT,
    priority    INTEGER NOT NULL DEFAULT 0,
    source      TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_category_rules_pattern ON category_rules(pattern);

CREATE TABLE budgets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    category_l1     TEXT NOT NULL,
    monthly_limit   REAL NOT NULL,
    effective_from  TEXT NOT NULL,
    effective_until TEXT,
    alert_threshold REAL NOT NULL DEFAULT 0.8,
    is_active       INTEGER NOT NULL DEFAULT 1,
    entity          TEXT NOT NULL DEFAULT 'personal'
);

CREATE TABLE settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT NOT NULL
);
