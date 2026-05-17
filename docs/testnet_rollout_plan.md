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
- print `result=DRY_RUN_NO_ORDER`

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

