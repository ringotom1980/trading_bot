-- Path: storage/schema/004_trades_log.sql
-- 說明：新增 trades_log 資料表，用於記錄完整已結束交易結果。

BEGIN;

CREATE TABLE IF NOT EXISTS trades_log (
    trade_id BIGSERIAL PRIMARY KEY,
    position_id BIGINT NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    interval VARCHAR(16) NOT NULL,
    engine_mode VARCHAR(16) NOT NULL,
    trade_mode VARCHAR(16) NULL,
    strategy_version_id BIGINT NOT NULL,
    side VARCHAR(16) NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    exit_time TIMESTAMPTZ NOT NULL,
    entry_price NUMERIC(20, 8) NOT NULL,
    exit_price NUMERIC(20, 8) NOT NULL,
    qty NUMERIC(20, 8) NOT NULL,
    gross_pnl NUMERIC(20, 8) NOT NULL,
    fees NUMERIC(20, 8) NOT NULL DEFAULT 0,
    net_pnl NUMERIC(20, 8) NOT NULL,
    bars_held INTEGER NULL,
    max_favorable_excursion NUMERIC(20, 8) NULL,
    max_adverse_excursion NUMERIC(20, 8) NULL,
    entry_decision_id BIGINT NULL,
    exit_decision_id BIGINT NULL,
    entry_order_id BIGINT NULL,
    exit_order_id BIGINT NULL,
    close_reason VARCHAR(32) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_trades_log_engine_mode
        CHECK (engine_mode IN ('BACKTEST', 'REALTIME')),

    CONSTRAINT chk_trades_log_trade_mode
        CHECK (trade_mode IS NULL OR trade_mode IN ('TESTNET', 'LIVE')),

    CONSTRAINT chk_trades_log_side
        CHECK (side IN ('LONG', 'SHORT')),

    CONSTRAINT chk_trades_log_close_reason
        CHECK (
            close_reason IS NULL
            OR close_reason IN ('SIGNAL_EXIT', 'REVERSE', 'STOP', 'MANUAL', 'FORCED')
        ),

    CONSTRAINT chk_trades_log_exit_gt_entry
        CHECK (exit_time > entry_time),

    CONSTRAINT fk_trades_log_position
        FOREIGN KEY (position_id)
        REFERENCES positions (position_id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_trades_log_strategy_version
        FOREIGN KEY (strategy_version_id)
        REFERENCES strategy_versions (strategy_version_id)
        ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_trades_log_position_id
    ON trades_log (position_id);

CREATE INDEX IF NOT EXISTS idx_trades_log_strategy_version_id
    ON trades_log (strategy_version_id);

CREATE INDEX IF NOT EXISTS idx_trades_log_symbol_interval
    ON trades_log (symbol, interval);

CREATE INDEX IF NOT EXISTS idx_trades_log_entry_time
    ON trades_log (entry_time);

CREATE INDEX IF NOT EXISTS idx_trades_log_exit_time
    ON trades_log (exit_time);

CREATE INDEX IF NOT EXISTS idx_trades_log_net_pnl
    ON trades_log (net_pnl);

COMMIT;