-- Path: storage/schema/005_orders.sql
-- 說明：新增 orders 資料表，用於記錄送單與委託狀態。

BEGIN;

CREATE TABLE IF NOT EXISTS orders (
    order_id BIGSERIAL PRIMARY KEY,
    position_id BIGINT NULL,
    symbol VARCHAR(32) NOT NULL,
    interval VARCHAR(16) NOT NULL,
    engine_mode VARCHAR(16) NOT NULL,
    trade_mode VARCHAR(16) NOT NULL,
    strategy_version_id BIGINT NOT NULL,
    client_order_id VARCHAR(128) NULL,
    exchange_order_id VARCHAR(128) NULL,
    side VARCHAR(16) NOT NULL,
    order_type VARCHAR(32) NOT NULL,
    reduce_only BOOLEAN NOT NULL DEFAULT FALSE,
    qty NUMERIC(20, 8) NOT NULL,
    price NUMERIC(20, 8) NULL,
    avg_price NUMERIC(20, 8) NULL,
    status VARCHAR(32) NOT NULL,
    exchange_status_raw VARCHAR(64) NULL,
    placed_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    filled_at TIMESTAMPTZ NULL,
    error_code VARCHAR(64) NULL,
    error_message TEXT NULL,
    raw_request_json JSONB NULL,
    raw_response_json JSONB NULL,

    CONSTRAINT chk_orders_engine_mode
        CHECK (engine_mode IN ('BACKTEST', 'REALTIME')),

    CONSTRAINT chk_orders_trade_mode
        CHECK (trade_mode IN ('TESTNET', 'LIVE')),

    CONSTRAINT chk_orders_side
        CHECK (side IN ('BUY', 'SELL')),

    CONSTRAINT chk_orders_order_type
        CHECK (order_type IN ('MARKET', 'LIMIT')),

    CONSTRAINT chk_orders_status
        CHECK (status IN ('NEW', 'PARTIALLY_FILLED', 'FILLED', 'CANCELED', 'REJECTED', 'EXPIRED')),

    CONSTRAINT fk_orders_position
        FOREIGN KEY (position_id)
        REFERENCES positions (position_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_orders_strategy_version
        FOREIGN KEY (strategy_version_id)
        REFERENCES strategy_versions (strategy_version_id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_orders_position_id
    ON orders (position_id);

CREATE INDEX IF NOT EXISTS idx_orders_exchange_order_id
    ON orders (exchange_order_id);

CREATE INDEX IF NOT EXISTS idx_orders_client_order_id
    ON orders (client_order_id);

CREATE INDEX IF NOT EXISTS idx_orders_status
    ON orders (status);

CREATE INDEX IF NOT EXISTS idx_orders_placed_at
    ON orders (placed_at);

CREATE INDEX IF NOT EXISTS idx_orders_strategy_version_id
    ON orders (strategy_version_id);

COMMIT;