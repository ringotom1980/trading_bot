-- Path: storage/schema/003_positions.sql
-- 說明：新增 positions 資料表，用於記錄持倉生命週期。

BEGIN;

CREATE TABLE IF NOT EXISTS positions (
    position_id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    interval VARCHAR(16) NOT NULL,
    engine_mode VARCHAR(16) NOT NULL,
    trade_mode VARCHAR(16) NULL,
    strategy_version_id BIGINT NOT NULL,
    side VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    entry_price NUMERIC(20, 8) NOT NULL,
    entry_qty NUMERIC(20, 8) NOT NULL,
    entry_notional NUMERIC(20, 8) NULL,
    exit_price NUMERIC(20, 8) NULL,
    exit_qty NUMERIC(20, 8) NULL,
    gross_pnl NUMERIC(20, 8) NULL,
    fees NUMERIC(20, 8) NOT NULL DEFAULT 0,
    net_pnl NUMERIC(20, 8) NULL,
    entry_order_id BIGINT NULL,
    entry_decision_id BIGINT NULL,
    exit_order_id BIGINT NULL,
    exit_decision_id BIGINT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ NULL,
    close_reason VARCHAR(32) NULL,
    exchange_position_ref VARCHAR(128) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_positions_engine_mode
        CHECK (engine_mode IN ('BACKTEST', 'REALTIME')),

    CONSTRAINT chk_positions_trade_mode
        CHECK (trade_mode IS NULL OR trade_mode IN ('TESTNET', 'LIVE')),

    CONSTRAINT chk_positions_side
        CHECK (side IN ('LONG', 'SHORT')),

    CONSTRAINT chk_positions_status
        CHECK (status IN ('OPEN', 'CLOSED')),

    CONSTRAINT chk_positions_close_reason
        CHECK (
            close_reason IS NULL
            OR close_reason IN ('SIGNAL_EXIT', 'REVERSE', 'STOP', 'MANUAL', 'FORCED')
        ),

    CONSTRAINT chk_positions_open_closed_fields
        CHECK (
            (status = 'OPEN' AND closed_at IS NULL)
            OR
            (status = 'CLOSED' AND closed_at IS NOT NULL)
        ),

    CONSTRAINT fk_positions_strategy_version
        FOREIGN KEY (strategy_version_id)
        REFERENCES strategy_versions (strategy_version_id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_positions_entry_decision
        FOREIGN KEY (entry_decision_id)
        REFERENCES decisions_log (decision_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_positions_exit_decision
        FOREIGN KEY (exit_decision_id)
        REFERENCES decisions_log (decision_id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_positions_strategy_version_id
    ON positions (strategy_version_id);

CREATE INDEX IF NOT EXISTS idx_positions_status
    ON positions (status);

CREATE INDEX IF NOT EXISTS idx_positions_opened_at
    ON positions (opened_at);

CREATE INDEX IF NOT EXISTS idx_positions_closed_at
    ON positions (closed_at);

CREATE UNIQUE INDEX IF NOT EXISTS uq_positions_single_open_symbol
    ON positions (symbol)
    WHERE status = 'OPEN';

COMMIT;