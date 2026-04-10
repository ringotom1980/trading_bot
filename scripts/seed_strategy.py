"""
Path: scripts/seed_strategy.py
說明：建立第一版初始策略與 system_state，讓系統具備可啟動的基本種子資料。
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.logging import get_logger, setup_logging
from config.settings import load_settings
from storage.db import connection_scope, test_connection
from storage.repositories.strategy_versions_repo import (
    create_strategy_version,
    get_strategy_version_by_code,
)
from storage.repositories.system_state_repo import (
    create_initial_system_state,
    get_system_state,
)


def build_initial_feature_set() -> dict:
    """
    功能：建立第一版策略特徵集合定義。
    回傳：
        第一版 feature_set 字典。
    """
    return {
        "version": 2,
        "features": [
            "rsi_14",
            "macd_dif",
            "macd_dea",
            "macd_hist",
            "kd_k",
            "kd_d",
            "kd_diff",
            "close_vs_sma20_pct",
            "close_vs_sma60_pct",
            "slope_5",
            "slope_10",
            "atr_14_pct",
            "volatility_10",
            "volume_ratio_20",
            "volume_slope_5",
            "regime",
            "regime_score",
        ],
        "regime_values": [
            "TREND_UP",
            "TREND_DOWN",
            "RANGE",
        ],
    }


def build_initial_params() -> dict:
    """
    功能：建立第一版策略預設參數。
    回傳：
        第一版 params 字典。
    """
    return {
        "entry_threshold": 0.62,
        "exit_threshold": 0.42,
        "reverse_threshold": 0.70,
        "reverse_gap": 0.12,
        "min_hold_bars": 2,
        "cooldown_bars": 2,
        "hard_stop_loss_pct": 0.018,
        "take_profit_pct": 0.0,
        "max_bars_hold": 18,
        "fee_rate": 0.0004,
        "slippage_rate": 0.0005,
        "weights": {
            "long": {
                "rsi_14": 0.10,
                "macd_hist": 0.14,
                "kd_diff": 0.08,
                "close_vs_sma20_pct": 0.12,
                "close_vs_sma60_pct": 0.12,
                "slope_5": 0.10,
                "slope_10": 0.10,
                "atr_14_pct": -0.05,
                "volatility_10": -0.04,
                "volume_ratio_20": 0.07,
                "volume_slope_5": 0.04,
                "regime_score": 0.12,
            },
            "short": {
                "rsi_14": 0.10,
                "macd_hist": 0.14,
                "kd_diff": 0.08,
                "close_vs_sma20_pct": 0.12,
                "close_vs_sma60_pct": 0.12,
                "slope_5": 0.10,
                "slope_10": 0.10,
                "atr_14_pct": -0.05,
                "volatility_10": -0.04,
                "volume_ratio_20": 0.07,
                "volume_slope_5": 0.04,
                "regime_score": 0.12,
            },
        },
    }


def seed_initial_strategy() -> None:
    """
    功能：建立第一版策略與 system_state，若已存在則略過。
    """
    logger = get_logger("scripts.seed_strategy")
    settings = load_settings()

    version_code = "btc15m_v002"

    with connection_scope() as conn:
        existing_strategy = get_strategy_version_by_code(conn, version_code)

        if existing_strategy is None:
            strategy_version_id = create_strategy_version(
                conn=conn,
                version_code=version_code,
                status="RETIRED",
                source_type="MANUAL",
                symbol=settings.primary_symbol,
                interval=settings.primary_interval,
                feature_set=build_initial_feature_set(),
                params=build_initial_params(),
                note="第二版 base search seed 策略",
            )
            logger.info("已建立 base search seed 策略：version_code=%s, strategy_version_id=%s", version_code, strategy_version_id)
        else:
            strategy_version_id = int(existing_strategy["strategy_version_id"])
            logger.info("初始策略已存在，略過建立：version_code=%s, strategy_version_id=%s", version_code, strategy_version_id)

        existing_state = get_system_state(conn, 1)

        if existing_state is None:
            create_initial_system_state(
                conn=conn,
                active_strategy_version_id=strategy_version_id,
                primary_symbol=settings.primary_symbol,
                primary_interval=settings.primary_interval,
            )
            logger.info("已建立 system_state 初始資料：id=1")
        else:
            logger.info("system_state 已存在，略過建立：id=1")


def main() -> None:
    """
    功能：種子資料腳本主入口。
    """
    setup_logging()
    logger = get_logger("scripts.seed_strategy")

    ok, message = test_connection()
    if not ok:
        logger.error(message)
        raise SystemExit(1)

    logger.info(message)
    seed_initial_strategy()


if __name__ == "__main__":
    main()