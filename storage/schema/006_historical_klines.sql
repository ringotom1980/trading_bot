-- Path: storage/schema/006_historical_klines.sql
-- 說明：新增 historical_klines 資料表，作為歷史 K 線唯一資料來源，供回測、驗證、候選策略研究使用。

BEGIN;

CREATE TABLE IF NOT EXISTS historical_klines (
    kline_id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    interval VARCHAR(16) NOT NULL,
    market_type VARCHAR(16) NOT NULL DEFAULT 'FUTURES',
    source VARCHAR(32) NOT NULL DEFAULT 'BINANCE',

    open_time TIMESTAMPTZ NOT NULL,
    close_time TIMESTAMPTZ NOT NULL,

    open NUMERIC(20, 8) NOT NULL,
    high NUMERIC(20, 8) NOT NULL,
    low NUMERIC(20, 8) NOT NULL,
    close NUMERIC(20, 8) NOT NULL,
    volume NUMERIC(28, 8) NOT NULL,

    quote_asset_volume NUMERIC(28, 8) NULL,
    trade_count INTEGER NULL,
    taker_buy_base_volume NUMERIC(28, 8) NULL,
    taker_buy_quote_volume NUMERIC(28, 8) NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_historical_klines_market_type
        CHECK (market_type IN ('FUTURES')),

    CONSTRAINT chk_historical_klines_source
        CHECK (source IN ('BINANCE')),

    CONSTRAINT chk_historical_klines_price_non_negative
        CHECK (
            open >= 0
            AND high >= 0
            AND low >= 0
            AND close >= 0
            AND volume >= 0
        ),

    CONSTRAINT chk_historical_klines_high_low
        CHECK (
            high >= low
            AND high >= open
            AND high >= close
            AND low <= open
            AND low <= close
        ),

    CONSTRAINT chk_historical_klines_close_gt_open
        CHECK (close_time > open_time)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_historical_klines_symbol_interval_open_time
    ON historical_klines (symbol, interval, open_time);

CREATE INDEX IF NOT EXISTS idx_historical_klines_symbol_interval_close_time
    ON historical_klines (symbol, interval, close_time);

CREATE INDEX IF NOT EXISTS idx_historical_klines_symbol_interval_open_time
    ON historical_klines (symbol, interval, open_time);

COMMIT;