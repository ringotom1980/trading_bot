-- Path: storage/schema/001_init.sql
-- 說明：初始化第一版核心資料表，先建立 strategy_versions 與 system_state。

BEGIN;

CREATE TABLE IF NOT EXISTS strategy_versions (
    strategy_version_id BIGSERIAL PRIMARY KEY,
    version_code VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL,
    source_type VARCHAR(20) NOT NULL,
    base_version_id BIGINT NULL,
    symbol VARCHAR(32) NOT NULL,
    interval VARCHAR(16) NOT NULL,
    feature_set_json JSONB NOT NULL,
    params_json JSONB NOT NULL,
    backtest_summary_json JSONB NULL,
    validation_summary_json JSONB NULL,
    promotion_score NUMERIC(12, 6) NULL,
    is_candidate BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at TIMESTAMPTZ NULL,
    retired_at TIMESTAMPTZ NULL,
    note TEXT NULL,
    CONSTRAINT chk_strategy_versions_status
        CHECK (status IN ('DRAFT', 'CANDIDATE', 'ACTIVE', 'RETIRED')),
    CONSTRAINT chk_strategy_versions_source_type
        CHECK (source_type IN ('MANUAL', 'EVOLVED'))
);

CREATE INDEX IF NOT EXISTS idx_strategy_versions_status
    ON strategy_versions (status);

CREATE INDEX IF NOT EXISTS idx_strategy_versions_created_at
    ON strategy_versions (created_at);

CREATE INDEX IF NOT EXISTS idx_strategy_versions_base_version_id
    ON strategy_versions (base_version_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_strategy_versions_single_active
    ON strategy_versions ((status))
    WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS system_state (
    id BIGINT PRIMARY KEY,
    engine_mode VARCHAR(16) NOT NULL,
    trade_mode VARCHAR(16) NULL,
    trading_state VARCHAR(20) NOT NULL,
    live_armed BOOLEAN NOT NULL DEFAULT FALSE,
    active_strategy_version_id BIGINT NULL,
    primary_symbol VARCHAR(32) NOT NULL,
    primary_interval VARCHAR(16) NOT NULL,
    current_position_side VARCHAR(16) NULL,
    current_position_id BIGINT NULL,
    last_bar_close_time TIMESTAMPTZ NULL,
    last_decision_id BIGINT NULL,
    last_order_id BIGINT NULL,
    last_trade_id BIGINT NULL,
    last_heartbeat_at TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by VARCHAR(64) NULL,
    note TEXT NULL,
    CONSTRAINT chk_system_state_engine_mode
        CHECK (engine_mode IN ('BACKTEST', 'REALTIME')),
    CONSTRAINT chk_system_state_trade_mode
        CHECK (trade_mode IS NULL OR trade_mode IN ('TESTNET', 'LIVE')),
    CONSTRAINT chk_system_state_trading_state
        CHECK (trading_state IN ('ON', 'ENTRY_FROZEN', 'OFF')),
    CONSTRAINT chk_system_state_position_side
        CHECK (current_position_side IS NULL OR current_position_side IN ('LONG', 'SHORT')),
    CONSTRAINT chk_system_state_backtest_rules
        CHECK (
            (engine_mode = 'BACKTEST' AND trade_mode IS NULL AND live_armed = FALSE)
            OR
            (engine_mode = 'REALTIME')
        ),
    CONSTRAINT fk_system_state_active_strategy_version
        FOREIGN KEY (active_strategy_version_id)
        REFERENCES strategy_versions (strategy_version_id)
        ON DELETE SET NULL
);

COMMIT;