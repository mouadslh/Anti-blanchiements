-- Proposed PostgreSQL schema for data contract v1.
-- Labels are isolated from all tables consumed by the scoring service.

CREATE TABLE IF NOT EXISTS raw_transactions (
    tx_id TEXT PRIMARY KEY,
    event_ts TIMESTAMPTZ NOT NULL,
    source_account_id TEXT NOT NULL,
    target_account_id TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    currency TEXT NOT NULL DEFAULT 'MAD',
    channel TEXT NOT NULL CHECK (
        channel IN (
            'cash_deposit', 'cash_withdrawal', 'transfer', 'card', 'international_transfer'
        )
    ),
    source_customer_type TEXT NOT NULL CHECK (
        source_customer_type IN ('salaried', 'student', 'merchant', 'company')
    ),
    city TEXT NOT NULL,
    payload JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_raw_transactions_source_time
    ON raw_transactions (source_account_id, event_ts);
CREATE INDEX IF NOT EXISTS idx_raw_transactions_target_time
    ON raw_transactions (target_account_id, event_ts);

CREATE TABLE IF NOT EXISTS account_features (
    account_id TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    features JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, window_start, window_end),
    CHECK (window_end >= window_start)
);

CREATE TABLE IF NOT EXISTS scores (
    tx_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    risk_score NUMERIC NOT NULL CHECK (risk_score >= 0 AND risk_score <= 1),
    model_versions JSONB NOT NULL,
    scored_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scores_risk_time ON scores (risk_score DESC, scored_at DESC);

CREATE TABLE IF NOT EXISTS alerts (
    tx_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    risk_score NUMERIC NOT NULL CHECK (risk_score >= 0 AND risk_score <= 1),
    model_versions JSONB NOT NULL,
    explanation JSONB NOT NULL,
    alerted_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_alerts_risk_time ON alerts (risk_score DESC, alerted_at DESC);

CREATE TABLE IF NOT EXISTS labels (
    label_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id TEXT NOT NULL,
    tx_id TEXT,
    scenario TEXT NOT NULL,
    role TEXT NOT NULL,
    start_ts TIMESTAMPTZ NOT NULL,
    end_ts TIMESTAMPTZ,
    CHECK (end_ts IS NULL OR end_ts >= start_ts)
);

CREATE INDEX IF NOT EXISTS idx_labels_account_period
    ON labels (account_id, start_ts, end_ts);
CREATE INDEX IF NOT EXISTS idx_labels_tx_id ON labels (tx_id);
