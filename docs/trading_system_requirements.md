# Trading System Requirements

This project is a simulation-first Binance Futures trading bot for BTCUSDT.

## Target

Build a controlled self-learning trading system that can eventually trade live after it proves a positive edge in:

- historical backtests
- walk-forward validation
- Binance Futures Testnet execution
- monitored paper/live-candidate rollout

The goal is not to predict every top or bottom. The goal is to trade only when the system has a positive expected value, with controlled downside.

## Trading Scope

- Symbol: BTCUSDT only.
- Direction: long and short.
- Reversal: allowed, but implemented as close current position first, then open the opposite side after the close is confirmed.
- Initial leverage: 20x.
- Trading mode must be switchable by configuration and, later, by the web UI:
  - `SIMULATION`: local simulated execution, no exchange order placement.
  - `TESTNET`: Binance Futures Testnet order placement.
  - `LIVE`: Binance Futures live order placement, guarded by `LIVE_ARMED=true`.

## Safety Defaults

- Production VPS default must stay `TRADE_MODE=SIMULATION`.
- `TRADING_STATE=OFF` until a strategy passes validation and a reviewed activation step is ready.
- `LIVE_ARMED=false` unless deliberately preparing a live rollout.
- No autonomous live promotion.

## Risk Model

Risk is dynamic rather than a fixed "always exit after X loss" rule.

Position sizing should be based on:

- account equity
- risk percentage per trade
- ATR or volatility-derived stop distance
- leverage cap
- exchange quantity constraints
- hard maximum loss guard

Daily loss and drawdown controls should remain configurable:

- daily loss limit percentage
- daily loss limit USDT
- max consecutive losses
- cooldown after loss
- max strategy drawdown
- hard account drawdown cap

## Self-Learning Boundaries

The bot may:

- observe market regimes and trade outcomes
- diagnose where strategies fail
- generate candidate strategies
- run backtests and walk-forward validation
- place validated candidates into Testnet/paper trading

The bot must not:

- change live strategy and trade real funds without passing gates
- promote a strategy because it only won one recent trade
- increase risk after losses to recover
- bypass global safety state

## Research Workflow

1. Market diagnostics.
2. Baseline strategy comparison.
3. Strategy development only if it beats simple baselines after fees.
4. Walk-forward validation.
5. Testnet execution.
6. Monitored live-candidate rollout.
7. Small live activation only after explicit review.

