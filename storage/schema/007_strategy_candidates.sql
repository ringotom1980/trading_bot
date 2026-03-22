-- Path: storage/schema/007_strategy_candidates.sql
-- 說明：新增 strategy_candidates 資料表，用於保存 candidate search 結果，供人工審核與後續 promote 使用。

BEGIN;

CREATE TABLE IF NOT EXISTS strategy_candidates (
    candidate_id BIGSERIAL PRIMARY KEY,
    source_strategy_version_id BIGINT NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    interval VARCHAR(16) NOT NULL,
    tested_range_start TIMESTAMPTZ NOT NULL,
    tested_range_end TIMESTAMPTZ NOT NULL,
    candidate_no INTEGER NOT NULL,
    params_json JSONB NOT NULL,
    metrics_json JSONB NOT NULL,
    rank_score NUMERIC(20, 8) NOT NULL,
    candidate_status VARCHAR(20) NOT NULL DEFAULT 'NEW',
    note TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_strategy_candidates_status
        CHECK (candidate_status IN ('NEW', 'REVIEWED', 'APPROVED', 'REJECTED')),

    CONSTRAINT chk_strategy_candidates_range
        CHECK (tested_range_end > tested_range_start),

    CONSTRAINT fk_strategy_candidates_source_strategy
        FOREIGN KEY (source_strategy_version_id)
        REFERENCES strategy_versions (strategy_version_id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_strategy_candidates_source_strategy
    ON strategy_candidates (source_strategy_version_id);

CREATE INDEX IF NOT EXISTS idx_strategy_candidates_symbol_interval
    ON strategy_candidates (symbol, interval);

CREATE INDEX IF NOT EXISTS idx_strategy_candidates_created_at
    ON strategy_candidates (created_at);

CREATE INDEX IF NOT EXISTS idx_strategy_candidates_rank_score
    ON strategy_candidates (rank_score DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_strategy_candidates_unique_run_item
    ON strategy_candidates (
        source_strategy_version_id,
        symbol,
        interval,
        tested_range_start,
        tested_range_end,
        candidate_no
    );

COMMIT;