# trading_bot

Self-learning trading bot research project for Binance Futures.

Current goal: build a reliable simulation-first research workflow before any live trading.

The project is now moving away from blind parameter search. The new workflow is:

1. diagnose market regimes
2. compare simple baselines
3. build strategies only when they beat baselines after fees/slippage
4. validate with walk-forward and Testnet
5. switch to live only through explicit safety gates

See `docs/trading_system_requirements.md` for the current product and safety requirements.

## Current Safety Policy

- Keep VPS `.env` at `TRADE_MODE=SIMULATION`.
- Keep `TRADING_STATE=OFF` until a strategy passes long-range backtest and walk-forward validation.
- Keep `LIVE_ARMED=false` unless intentionally preparing a separately reviewed live rollout.
- Do not run `auto_promote_best_candidate.py` or `run_weekly_cycle.py` as unattended automation yet.

## Main Workflow

1. Health check:

   ```bash
   bash scripts/healthcheck_vps.sh
   python scripts/check_state.py
   ```

2. Sync historical data:

   ```bash
   python scripts/sync_historical_klines.py --start-date 2025-05-01 --end-date 2026-05-15
   ```

3. Run market diagnostics and baselines:

   ```bash
   python scripts/run_market_diagnostics.py --start-date 2025-05-01 --end-date 2026-05-15
   ```

4. Backtest a known strategy:

   ```bash
   python scripts/run_backtest.py --version-code btc15m_v002 --start-date 2025-05-01 --end-date 2026-05-15
   ```

5. Search candidates only after baselines and diagnostics justify the direction:

   ```bash
   python scripts/run_candidate_search.py --version-code btc15m_v002 --start-date 2025-05-01 --end-date 2026-03-01 --max-candidates 120 --top 10 --progress-step 20
   ```

6. Save and validate only if candidates pass the gate.

## Promotion Rule of Thumb

A candidate is not useful just because it beats the current active strategy.
It must be profitable after fees/slippage on a long training range and survive out-of-sample walk-forward validation.

Minimum expectations before simulation trading:

- `net_pnl > 0`
- `profit_factor >= 1.20`
- positive `avg_trade_pnl`
- reasonable trade count, not overtrading
- drawdown meaningfully smaller than expected profit
- out-of-sample validation remains positive

## Project Map

- `main.py` - runtime entrypoint.
- `core/` - state machine, guards, heartbeat, runtime loop.
- `strategy/` - features, signal scoring, decisions.
- `backtest/` - replay engine and metrics.
- `risk/` - dynamic risk sizing and guard helpers.
- `evolver/` - candidate generation, scoring, walk-forward, promotion checks.
- `governor/` - diagnostics-driven search space adjustment.
- `exchange/` - Binance client and market/order APIs.
- `services/` - runtime decision/execution services.
- `storage/` - PostgreSQL access, schema, repositories.
- `scripts/` - operational and research commands. See `scripts/README.md`.
