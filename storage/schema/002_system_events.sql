-- Path: storage/schema/002_system_events.sql
-- 說明：新增 system_events 資料表，用於記錄系統層級重大事件與稽核紀錄。

BEGIN;

CREATE TABLE IF NOT EXISTS system_events (
    event_id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(32) NOT NULL,
    event_level VARCHAR(16) NOT NULL,
    source VARCHAR(16) NOT NULL,
    engine_mode_before VARCHAR(16) NULL,
    engine_mode_after VARCHAR(16) NULL,
    trade_mode_before VARCHAR(16) NULL,
    trade_mode_after VARCHAR(16) NULL,
    trading_state_before VARCHAR(20) NULL,
    trading_state_after VARCHAR(20) NULL,
    live_armed_before BOOLEAN NULL,
    live_armed_after BOOLEAN NULL,
    strategy_version_before BIGINT NULL,
    strategy_version_after BIGINT NULL,
    message TEXT NULL,
    details_json JSONB NULL,
    created_by VARCHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_system_events_event_level
        CHECK (event_level IN ('INFO', 'WARN', 'ERROR', 'CRITICAL')),

    CONSTRAINT chk_system_events_source
        CHECK (source IN ('SYSTEM', 'AUTO', 'MANUAL')),

    CONSTRAINT chk_system_events_engine_mode_before
        CHECK (engine_mode_before IS NULL OR engine_mode_before IN ('BACKTEST', 'REALTIME')),

    CONSTRAINT chk_system_events_engine_mode_after
        CHECK (engine_mode_after IS NULL OR engine_mode_after IN ('BACKTEST', 'REALTIME')),

    CONSTRAINT chk_system_events_trade_mode_before
        CHECK (trade_mode_before IS NULL OR trade_mode_before IN ('TESTNET', 'LIVE')),

    CONSTRAINT chk_system_events_trade_mode_after
        CHECK (trade_mode_after IS NULL OR trade_mode_after IN ('TESTNET', 'LIVE')),

    CONSTRAINT chk_system_events_trading_state_before
        CHECK (trading_state_before IS NULL OR trading_state_before IN ('ON', 'ENTRY_FROZEN', 'OFF')),

    CONSTRAINT chk_system_events_trading_state_after
        CHECK (trading_state_after IS NULL OR trading_state_after IN ('ON', 'ENTRY_FROZEN', 'OFF'))
);

CREATE INDEX IF NOT EXISTS idx_system_events_event_type
    ON system_events (event_type);

CREATE INDEX IF NOT EXISTS idx_system_events_event_level
    ON system_events (event_level);

CREATE INDEX IF NOT EXISTS idx_system_events_source
    ON system_events (source);

CREATE INDEX IF NOT EXISTS idx_system_events_created_at
    ON system_events (created_at);

CREATE INDEX IF NOT EXISTS idx_system_events_strategy_version_after
    ON system_events (strategy_version_after);

COMMIT;