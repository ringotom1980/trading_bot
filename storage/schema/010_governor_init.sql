-- Path: storage/schema/010_governor_init.sql
-- 說明：初始化 v14 governor 最小可用資料表：
-- 1) governor_decisions
-- 2) family_performance_summary
-- 3) feature_diagnostics_summary
-- 4) search_space_config

BEGIN;

CREATE TABLE IF NOT EXISTS governor_decisions (
    decision_id BIGSERIAL PRIMARY KEY,
    run_key VARCHAR(128) NOT NULL,
    decision_type VARCHAR(32) NOT NULL,
    target_type VARCHAR(32) NOT NULL,
    target_key VARCHAR(128) NOT NULL,
    action VARCHAR(32) NOT NULL,
    before_value_json JSONB NULL,
    after_value_json JSONB NULL,
    reason_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_governor_decisions_decision_type
        CHECK (
            decision_type IN (
                'SEARCH_SPACE_ADJUST',
                'FAMILY_WEIGHT_ADJUST',
                'FEATURE_WEIGHT_ADJUST',
                'GATE_ADJUST',
                'VALIDATION_POLICY_ADJUST'
            )
        ),

    CONSTRAINT chk_governor_decisions_target_type
        CHECK (
            target_type IN (
                'SEARCH_SPACE',
                'FAMILY',
                'FEATURE',
                'GATE',
                'VALIDATION_POLICY'
            )
        ),

    CONSTRAINT chk_governor_decisions_action
        CHECK (
            action IN (
                'INCREASE',
                'DECREASE',
                'ENABLE',
                'DISABLE',
                'TIGHTEN',
                'LOOSEN',
                'REPLACE',
                'KEEP'
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_governor_decisions_run_key
    ON governor_decisions (run_key);

CREATE INDEX IF NOT EXISTS idx_governor_decisions_decision_type
    ON governor_decisions (decision_type);

CREATE INDEX IF NOT EXISTS idx_governor_decisions_target_type_target_key
    ON governor_decisions (target_type, target_key);

CREATE INDEX IF NOT EXISTS idx_governor_decisions_created_at
    ON governor_decisions (created_at DESC);


CREATE TABLE IF NOT EXISTS family_performance_summary (
    summary_id BIGSERIAL PRIMARY KEY,
    family_key VARCHAR(128) NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    interval VARCHAR(16) NOT NULL,

    sample_count INTEGER NOT NULL DEFAULT 0,
    pass_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,

    avg_rank_score NUMERIC(20, 8) NOT NULL DEFAULT 0,
    avg_net_pnl NUMERIC(20, 8) NOT NULL DEFAULT 0,
    avg_profit_factor NUMERIC(20, 8) NOT NULL DEFAULT 0,
    avg_max_drawdown NUMERIC(20, 8) NOT NULL DEFAULT 0,

    last_run_at TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_family_performance_summary_counts
        CHECK (
            sample_count >= 0
            AND pass_count >= 0
            AND fail_count >= 0
            AND pass_count + fail_count <= sample_count
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_family_performance_summary_family_symbol_interval
    ON family_performance_summary (family_key, symbol, interval);

CREATE INDEX IF NOT EXISTS idx_family_performance_summary_symbol_interval
    ON family_performance_summary (symbol, interval);

CREATE INDEX IF NOT EXISTS idx_family_performance_summary_updated_at
    ON family_performance_summary (updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_family_performance_summary_last_run_at
    ON family_performance_summary (last_run_at DESC);


CREATE TABLE IF NOT EXISTS feature_diagnostics_summary (
    summary_id BIGSERIAL PRIMARY KEY,
    feature_key VARCHAR(128) NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    interval VARCHAR(16) NOT NULL,

    winner_avg NUMERIC(20, 8) NOT NULL DEFAULT 0,
    loser_avg NUMERIC(20, 8) NOT NULL DEFAULT 0,
    winner_count INTEGER NOT NULL DEFAULT 0,
    loser_count INTEGER NOT NULL DEFAULT 0,
    diagnostic_score NUMERIC(20, 8) NOT NULL DEFAULT 0,

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_feature_diagnostics_summary_counts
        CHECK (
            winner_count >= 0
            AND loser_count >= 0
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_feature_diagnostics_summary_feature_symbol_interval
    ON feature_diagnostics_summary (feature_key, symbol, interval);

CREATE INDEX IF NOT EXISTS idx_feature_diagnostics_summary_symbol_interval
    ON feature_diagnostics_summary (symbol, interval);

CREATE INDEX IF NOT EXISTS idx_feature_diagnostics_summary_diagnostic_score
    ON feature_diagnostics_summary (diagnostic_score DESC);

CREATE INDEX IF NOT EXISTS idx_feature_diagnostics_summary_updated_at
    ON feature_diagnostics_summary (updated_at DESC);


CREATE TABLE IF NOT EXISTS search_space_config (
    config_id BIGSERIAL PRIMARY KEY,
    scope_key VARCHAR(128) NOT NULL,
    config_version INTEGER NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by VARCHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_search_space_config_version
        CHECK (config_version > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_search_space_config_scope_version
    ON search_space_config (scope_key, config_version);

CREATE UNIQUE INDEX IF NOT EXISTS uq_search_space_config_single_active_scope
    ON search_space_config (scope_key)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_search_space_config_scope_key
    ON search_space_config (scope_key);

CREATE INDEX IF NOT EXISTS idx_search_space_config_is_active
    ON search_space_config (is_active);

CREATE INDEX IF NOT EXISTS idx_search_space_config_updated_at
    ON search_space_config (updated_at DESC);

COMMIT;