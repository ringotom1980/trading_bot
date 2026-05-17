# scripts guide

This directory is kept intentionally small for the live research workflow.

## Safe operational checks

- `healthcheck_vps.sh` - compile, dependency, settings, DB, and Binance public-kline check. Does not trade.
- `check_state.py` - print DB state, active strategy, latest decision/order/trade/event.
- `check_latest_events.py` - print recent system events for runtime diagnostics.
- `check_momentum_signal.py` - read-only current signal check for the long-horizon momentum candidate.
- `run_momentum_testnet_cycle.py` - dry-run/Testnet cycle for the momentum candidate; defaults to no order.
- `init_db.py` - apply all SQL files in `storage/schema` in sorted order.
- `seed_strategy.py` - create initial strategy/system state if missing.
- `sync_historical_klines.py` - fetch and upsert historical Binance futures klines.

## Research workflow

- `run_market_diagnostics.py` - diagnose market range/regime and compare simple baselines.
- `run_regime_strategy_backtest.py` - test the regime-first low-frequency swing strategy.
- `run_momentum_strategy_backtest.py` - test the long-horizon momentum swing strategy.
- `run_backtest.py` - backtest one strategy version over a date range.
- `run_candidate_search.py` - generate and backtest candidates without saving them.
- `run_candidate_search_and_save.py` - generate, backtest, and save candidates.
- `run_walk_forward_validation.py` - validate saved candidates over walk-forward windows.
- `validate_candidate_range.py` - validate one or more candidates over a fixed range.
- `inspect_candidate_gate_failures.py` - inspect why candidates fail the gate.
- `inspect_strategy_scores.py` - inspect strategy scoring behavior.
- `rebuild_family_performance_summary.py` - rebuild governor family summary from candidates.
- `rebuild_feature_diagnostics_summary.py` - rebuild governor feature diagnostics summary.
- `run_governor_cycle.py` - adjust future search space from diagnostics.

## Automation and promotion

- `run_weekly_cycle.py` - full automated research cycle. Keep disabled until the research workflow is trustworthy.
- `auto_promote_best_candidate.py` - promote candidates. Keep disabled until promotion gates and validation are proven.

## Runtime service helpers

- `start_bot.sh`
- `stop_bot.sh`
- `restart_bot.sh`
- `status_bot.sh`
- `logs_bot.sh`
- `start_momentum_dry_run.sh`
- `stop_momentum_dry_run.sh`
- `status_momentum_dry_run.sh`
- `logs_momentum_dry_run.sh`

## Manual or dangerous tools

Use only with explicit intent:

- `reset_db.py`
- `reset_demo_data.py`
- `reset_governor_demo_data.py`
- `testnet_force_order.py`
- `sync_system_state_position.py`
- `backfill_historical_klines.py`
- `bootstrap_search_space_config.py`

## Legacy

`scripts/legacy` contains early one-off checks, demo scripts, and old per-schema apply wrappers.
They are retained for reference, but should not be part of the normal workflow.
