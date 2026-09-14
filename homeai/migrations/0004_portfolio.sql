-- Phase F: market data, theses.

CREATE TABLE prices_daily (
    symbol      TEXT NOT NULL,
    as_of       TEXT NOT NULL,
    close       REAL NOT NULL,
    source      TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (symbol, as_of)
);

CREATE TABLE macro_daily (
    series      TEXT NOT NULL,           -- wti_usd, ust_3m, ust_2y, ust_10y, ust_30y, btc_usd, eth_usd, ...
    as_of       TEXT NOT NULL,
    value       REAL NOT NULL,
    source      TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (series, as_of)
);

CREATE TABLE theses (
    slug          TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    view          TEXT NOT NULL,         -- the opinion, in the user's words
    status        TEXT NOT NULL DEFAULT 'draft',   -- draft | active | closed
    conviction    INTEGER NOT NULL DEFAULT 2,      -- 1..3
    budget_pct    REAL NOT NULL DEFAULT 0,         -- share of the thesis sleeve cap
    horizon_start TEXT,
    horizon_end   TEXT,
    benchmark     TEXT,                  -- symbol the thesis is judged against
    exit_rules    TEXT,
    kill_metrics  TEXT,                  -- JSON [{series, op, level, note}]
    notes         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    closed_at     TEXT
);

CREATE TABLE thesis_legs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    thesis_slug   TEXT NOT NULL REFERENCES theses(slug),
    symbol        TEXT NOT NULL,
    direction     TEXT NOT NULL DEFAULT 'long',    -- long | underweight
    target_weight REAL,                  -- share of the thesis budget
    account_id    TEXT REFERENCES accounts(id),
    opened_at     TEXT,
    closed_at     TEXT,
    entry_price   REAL,
    quantity      REAL,
    notes         TEXT,
    updated_at    TEXT NOT NULL
);
CREATE INDEX idx_thesis_legs_thesis ON thesis_legs(thesis_slug);
