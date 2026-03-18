-- Path: storage/schema/002_decisions_log.sql
-- 說明：新增 decisions_log 資料表，用於記錄每次策略判斷結果。

BEGIN;

CREATE TABLE IF NOT EXISTS decisions_log (
    decision_id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    interval VARCHAR(16) NOT NULL,
    bar_open_time TIMESTAMPTZ NOT NULL,
    bar_close_time TIMESTAMPTZ NOT NULL,
    engine_mode VARCHAR(16) NOT NULL,
    trade_mode VARCHAR(16) NULL,
    strategy_version_id BIGINT NOT NULL,
    position_id_before BIGINT NULL,
    position_side_before VARCHAR(16) NULL,
    decision VARCHAR(20) NOT NULL,
    decision_score NUMERIC(12, 6) NULL,
    reason_code VARCHAR(32) NULL,
    reason_summary TEXT NULL,
    features_json JSONB NULL,
    executed BOOLEAN NOT NULL DEFAULT FALSE,
    position_id_after BIGINT NULL,
    position_side_after VARCHAR(16) NULL,
    linked_order_id BIGINT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_decisions_log_engine_mode
        CHECK (engine_mode IN ('BACKTEST', 'REALTIME')),

    CONSTRAINT chk_decisions_log_trade_mode
        CHECK (trade_mode IS NULL OR trade_mode IN ('TESTNET', 'LIVE')),

    CONSTRAINT chk_decisions_log_decision
        CHECK (decision IN ('ENTER_LONG', 'ENTER_SHORT', 'EXIT', 'HOLD', 'WAIT')),

    CONSTRAINT chk_decisions_log_position_side_before
        CHECK (position_side_before IS NULL OR position_side_before IN ('LONG', 'SHORT')),

    CONSTRAINT chk_decisions_log_position_side_after
        CHECK (position_side_after IS NULL OR position_side_after IN ('LONG', 'SHORT')),

    CONSTRAINT fk_decisions_log_strategy_version
        FOREIGN KEY (strategy_version_id)
        REFERENCES strategy_versions (strategy_version_id)
        ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_decisions_log_symbol_interval_bar_close_time
    ON decisions_log (symbol, interval, bar_close_time);

CREATE INDEX IF NOT EXISTS idx_decisions_log_strategy_version_id
    ON decisions_log (strategy_version_id);

CREATE INDEX IF NOT EXISTS idx_decisions_log_decision
    ON decisions_log (decision);

CREATE INDEX IF NOT EXISTS idx_decisions_log_created_at
    ON decisions_log (created_at);

CREATE INDEX IF NOT EXISTS idx_decisions_log_executed
    ON decisions_log (executed);

COMMIT;