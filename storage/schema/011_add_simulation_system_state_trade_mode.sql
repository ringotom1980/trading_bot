-- Path: storage/schema/011_add_simulation_system_state_trade_mode.sql
-- 說明：擴充 system_state.trade_mode 約束，加入 SIMULATION。

BEGIN;

ALTER TABLE system_state
    DROP CONSTRAINT IF EXISTS chk_system_state_trade_mode;

ALTER TABLE system_state
    ADD CONSTRAINT chk_system_state_trade_mode
    CHECK (trade_mode IS NULL OR trade_mode IN ('SIMULATION', 'TESTNET', 'LIVE'));

COMMIT;
