# Research Notes - 2026-05-17

## Why The Direction Changed

The previous workflow kept searching for parameter combinations inside a weak 15m signal framework. That produced repeated failures:

- too many trades
- fee drag
- strategies that work in one regime but fail in another
- recent one-trade winners that fail older validation

The project should keep its infrastructure, but the strategy research core must change.

## Baseline Diagnostics

Range: 2025-05-01 to 2026-05-15

- BTCUSDT close return: -13.98%
- Regime scan: mostly RANGE, with similar TREND_UP and TREND_DOWN counts
- Buy and hold long: -133.32 USDT
- Buy and hold short: +130.17 USDT
- SMA60/240 regime flip: -329.09 USDT
- Channel96 breakout: -220.84 USDT

Older range: 2025-05-01 to 2026-03-01

- BTCUSDT close return: -28.96%
- Buy and hold short: +271.41 USDT
- Channel96 breakout almost flat but still negative after fees: -51.52 USDT

Recent range: 2026-03-01 to 2026-05-15

- BTCUSDT close return: +21.18%
- Buy and hold long: +140.32 USDT
- SMA60/240 regime flip: -7.54 USDT
- Channel96 breakout: -123.18 USDT

## Interpretation

The first real edge to investigate is not fast 15m signal scoring. It is regime selection:

- when the market is broadly down, short exposure dominates
- when the market is broadly up, long exposure dominates
- frequent switching destroys results through fees

The next strategy family should be low-frequency, regime-first, and volatility-sized.

## Next Build Direction

1. Build a regime-first baseline that can stay flat when the regime is unclear.
2. Add dynamic position sizing from account equity and ATR/volatility.
3. Add daily loss and drawdown guards.
4. Validate on older, recent, and full ranges.
5. Only then connect to Testnet execution.

