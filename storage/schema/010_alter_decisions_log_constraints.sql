BEGIN;

ALTER TABLE decisions_log
DROP CONSTRAINT IF EXISTS chk_decisions_log_trade_mode;

ALTER TABLE decisions_log
ADD CONSTRAINT chk_decisions_log_trade_mode
CHECK (
    trade_mode IS NULL
    OR trade_mode IN ('SIMULATION', 'TESTNET', 'LIVE')
);

ALTER TABLE decisions_log
DROP CONSTRAINT IF EXISTS chk_decisions_log_decision;

ALTER TABLE decisions_log
ADD CONSTRAINT chk_decisions_log_decision
CHECK (
    decision IN (
        'ENTER_LONG',
        'ENTER_SHORT',
        'EXIT',
        'EXIT_HARD',
        'EXIT_WEAK',
        'HOLD',
        'WAIT'
    )
);

COMMIT;