# Testnet Rollout Plan

This document defines how to move from read-only research into Binance Futures Testnet execution.

## Current Default

The VPS should remain:

```text
TRADE_MODE=SIMULATION
TRADING_STATE=OFF
LIVE_ARMED=false
```

In this state, `scripts/run_momentum_testnet_cycle.py` runs as a dry-run only and will not place orders.

## Dry-Run Check

```bash
python scripts/run_momentum_testnet_cycle.py
```

Expected behavior:

- fetch live public BTCUSDT klines
- calculate the long-horizon momentum signal
- read Binance Futures Testnet USDT balance
- read current Testnet BTCUSDT position
- calculate planned quantity and risk
- update local shadow paper-trading state
- print shadow realized/unrealized/total PnL
- print recent 2-hour and 24-hour market movement plus hypothetical 0.01 BTC long/short PnL
- print long/mid/short timeframe signals and each timeframe's shadow PnL
- print `result=DRY_RUN_NO_ORDER`

## Continuous Dry-Run Monitor

Run this before enabling Testnet execution:

```bash
bash scripts/start_momentum_dry_run.sh
bash scripts/status_momentum_dry_run.sh
bash scripts/logs_momentum_dry_run.sh
```

Stop it with:

```bash
bash scripts/stop_momentum_dry_run.sh
```

The loop runs every 15 minutes by default and only calls `run_momentum_testnet_cycle.py` without `--execute-testnet`, so it cannot place orders.

Shadow paper state is stored at:

```text
logs/momentum_shadow_state.json
```

This file tracks hypothetical dry-run position, trade count, realized PnL, unrealized PnL, and total PnL. It is not exchange state and it does not place orders.

The file also tracks per-timeframe shadow strategies:

- `long`: 1920-bar momentum, threshold 3%, confirmation 96 bars
- `mid`: 96-bar momentum, threshold 0.8%, confirmation 8 bars
- `short`: 32-bar momentum, threshold 0.3%, confirmation 4 bars

The combined signal is informational during dry-run. Testnet execution still remains disabled unless the explicit Testnet gate is opened later.

## Testnet Execution Gate

Actual Testnet orders require all of the following:

```text
TRADE_MODE=TESTNET
TRADING_STATE=ON
LIVE_ARMED=false
```

Then run:

```bash
python scripts/run_momentum_testnet_cycle.py --execute-testnet
```

The script will still do nothing if:

- signal is `FLAT`
- signal is not confirmed
- current position already matches the signal
- planned quantity is zero

## Live Trading Gate

This script does not support live execution. Live trading must be a separate reviewed rollout after Testnet performance is acceptable.
