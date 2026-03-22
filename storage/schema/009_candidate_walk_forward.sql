-- Path: storage/schema/009_candidate_walk_forward.sql
-- 說明：新增 candidate walk-forward run 與 window 明細表。

BEGIN;

CREATE TABLE IF NOT EXISTS candidate_walk_forward_runs (
    run_id BIGSERIAL PRIMARY KEY,
    candidate_id BIGINT NOT NULL,
    source_strategy_version_id BIGINT NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    interval VARCHAR(16) NOT NULL,

    train_range_start TIMESTAMPTZ NULL,
    train_range_end TIMESTAMPTZ NULL,
    validation_range_start TIMESTAMPTZ NOT NULL,
    validation_range_end TIMESTAMPTZ NOT NULL,

    window_days INTEGER NOT NULL,
    step_days INTEGER NOT NULL,

    total_windows INTEGER NOT NULL DEFAULT 0,
    pass_windows INTEGER NOT NULL DEFAULT 0,
    beat_active_windows INTEGER NOT NULL DEFAULT 0,
    pass_ratio NUMERIC(12, 6) NOT NULL DEFAULT 0,

    avg_net_pnl NUMERIC(20, 8) NOT NULL DEFAULT 0,
    avg_profit_factor NUMERIC(20, 8) NOT NULL DEFAULT 0,
    avg_max_drawdown NUMERIC(20, 8) NOT NULL DEFAULT 0,
    worst_window_net_pnl NUMERIC(20, 8) NOT NULL DEFAULT 0,
    worst_window_drawdown NUMERIC(20, 8) NOT NULL DEFAULT 0,

    active_avg_net_pnl NUMERIC(20, 8) NOT NULL DEFAULT 0,
    active_avg_profit_factor NUMERIC(20, 8) NOT NULL DEFAULT 0,
    active_avg_max_drawdown NUMERIC(20, 8) NOT NULL DEFAULT 0,

    final_status VARCHAR(20) NOT NULL DEFAULT 'FAIL',
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_candidate_walk_forward_runs_status
        CHECK (final_status IN ('PASS', 'FAIL')),

    CONSTRAINT chk_candidate_walk_forward_runs_window_days
        CHECK (window_days > 0),

    CONSTRAINT chk_candidate_walk_forward_runs_step_days
        CHECK (step_days > 0),

    CONSTRAINT chk_candidate_walk_forward_runs_range
        CHECK (validation_range_end > validation_range_start),

    CONSTRAINT fk_candidate_walk_forward_runs_candidate
        FOREIGN KEY (candidate_id)
        REFERENCES strategy_candidates (candidate_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_candidate_walk_forward_runs_strategy
        FOREIGN KEY (source_strategy_version_id)
        REFERENCES strategy_versions (strategy_version_id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_candidate_walk_forward_runs_candidate
    ON candidate_walk_forward_runs (candidate_id);

CREATE INDEX IF NOT EXISTS idx_candidate_walk_forward_runs_range
    ON candidate_walk_forward_runs (
        source_strategy_version_id,
        symbol,
        interval,
        validation_range_start,
        validation_range_end
    );

CREATE INDEX IF NOT EXISTS idx_candidate_walk_forward_runs_status
    ON candidate_walk_forward_runs (final_status, created_at DESC);

CREATE TABLE IF NOT EXISTS candidate_walk_forward_windows (
    window_id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL,
    window_no INTEGER NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,

    candidate_metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    active_metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,

    candidate_net_pnl NUMERIC(20, 8) NOT NULL DEFAULT 0,
    candidate_profit_factor NUMERIC(20, 8) NOT NULL DEFAULT 0,
    candidate_max_drawdown NUMERIC(20, 8) NOT NULL DEFAULT 0,
    candidate_total_trades INTEGER NOT NULL DEFAULT 0,

    active_net_pnl NUMERIC(20, 8) NOT NULL DEFAULT 0,
    active_profit_factor NUMERIC(20, 8) NOT NULL DEFAULT 0,
    active_max_drawdown NUMERIC(20, 8) NOT NULL DEFAULT 0,
    active_total_trades INTEGER NOT NULL DEFAULT 0,

    passed BOOLEAN NOT NULL DEFAULT FALSE,
    beat_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_candidate_walk_forward_windows_no
        CHECK (window_no > 0),

    CONSTRAINT chk_candidate_walk_forward_windows_range
        CHECK (window_end > window_start),

    CONSTRAINT fk_candidate_walk_forward_windows_run
        FOREIGN KEY (run_id)
        REFERENCES candidate_walk_forward_runs (run_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_candidate_walk_forward_windows_run_no
        UNIQUE (run_id, window_no)
);

CREATE INDEX IF NOT EXISTS idx_candidate_walk_forward_windows_run
    ON candidate_walk_forward_windows (run_id);

COMMIT;