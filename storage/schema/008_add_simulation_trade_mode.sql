-- Path: storage/schema/008_add_simulation_trade_mode.sql
-- 說明：擴充 orders / positions / trades_log 的 trade_mode 約束，加入 SIMULATION。

BEGIN;

ALTER TABLE orders
    DROP CONSTRAINT IF EXISTS chk_orders_trade_mode;

ALTER TABLE orders
    ADD CONSTRAINT chk_orders_trade_mode
    CHECK (trade_mode IN ('SIMULATION', 'TESTNET', 'LIVE'));

ALTER TABLE positions
    DROP CONSTRAINT IF EXISTS chk_positions_trade_mode;

ALTER TABLE positions
    ADD CONSTRAINT chk_positions_trade_mode
    CHECK (trade_mode IS NULL OR trade_mode IN ('SIMULATION', 'TESTNET', 'LIVE'));

ALTER TABLE trades_log
    DROP CONSTRAINT IF EXISTS chk_trades_log_trade_mode;

ALTER TABLE trades_log
    ADD CONSTRAINT chk_trades_log_trade_mode
    CHECK (trade_mode IS NULL OR trade_mode IN ('SIMULATION', 'TESTNET', 'LIVE'));

COMMIT;