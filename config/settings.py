"""
Path: config/settings.py
說明：統一讀取 .env 與環境變數，整理成可供全專案共用的設定物件。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from config.constants import ENGINE_MODES, TRADE_MODES, TRADING_STATES


def _project_root() -> Path:
    """
    功能：取得專案根目錄路徑。
    回傳：
        專案根目錄 Path 物件。
    """
    return Path(__file__).resolve().parent.parent


def _env_file_path() -> Path:
    """
    功能：取得 .env 檔案路徑。
    回傳：
        專案根目錄下的 .env 路徑。
    """
    return _project_root() / ".env"


def _load_env_file() -> None:
    """
    功能：若專案根目錄存在 .env，則先載入。
    """
    env_path = _env_file_path()
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)


def _get_env(name: str, default: str | None = None) -> str | None:
    """
    功能：讀取指定環境變數。
    參數：
        name: 環境變數名稱。
        default: 預設值。
    回傳：
        字串值或 None。
    """
    return os.getenv(name, default)


def _require_env(name: str) -> str:
    """
    功能：讀取必要環境變數，若缺少則丟出錯誤。
    參數：
        name: 必要環境變數名稱。
    回傳：
        環境變數字串值。
    """
    value = _get_env(name)
    if value is None or value == "":
        raise ValueError(f"缺少必要環境變數：{name}")
    return value


def _parse_bool(value: str | None, default: bool = False) -> bool:
    """
    功能：將字串解析為布林值。
    參數：
        value: 原始字串值。
        default: 預設布林值。
    回傳：
        解析後的布林值。
    """
    if value is None:
        return default

    normalized = value.strip().lower()
    return normalized in {"1", "true", "yes", "y", "on"}


def _parse_int(value: str | None, default: int) -> int:
    """
    功能：將字串解析為整數。
    參數：
        value: 原始字串值。
        default: 預設整數值。
    回傳：
        解析後的整數值。
    """
    if value is None or value == "":
        return default
    return int(value)


def _validate_choice(name: str, value: str | None, allowed: set[str], allow_none: bool = False) -> str | None:
    """
    功能：驗證設定值是否落在允許範圍內。
    參數：
        name: 設定名稱。
        value: 設定值。
        allowed: 允許值集合。
        allow_none: 是否允許 None。
    回傳：
        驗證後的原值。
    """
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"設定值不可為空：{name}")

    if value not in allowed:
        raise ValueError(f"設定值錯誤：{name}={value}，允許值：{sorted(allowed)}")

    return value


@dataclass(frozen=True)
class Settings:
    """
    功能：封裝全專案共用設定。
    """

    app_env: str

    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str

    binance_api_key: str
    binance_api_secret: str

    primary_symbol: str
    primary_interval: str

    engine_mode: str
    trade_mode: str | None
    trading_state: str
    live_armed: bool

    project_root: Path
    env_file: Path


def load_settings() -> Settings:
    """
    功能：載入並驗證專案設定，回傳 Settings 物件。
    回傳：
        完整設定物件。
    """
    _load_env_file()

    app_env = _get_env("APP_ENV", "development")

    db_host = _require_env("DB_HOST")
    db_port = _parse_int(_get_env("DB_PORT"), 5432)
    db_name = _require_env("DB_NAME")
    db_user = _require_env("DB_USER")
    db_password = _require_env("DB_PASSWORD")

    binance_api_key = _get_env("BINANCE_API_KEY", "") or ""
    binance_api_secret = _get_env("BINANCE_API_SECRET", "") or ""

    primary_symbol = _get_env("PRIMARY_SYMBOL", "BTCUSDT") or "BTCUSDT"
    primary_interval = _get_env("PRIMARY_INTERVAL", "15m") or "15m"

    engine_mode = _validate_choice(
        name="ENGINE_MODE",
        value=_get_env("ENGINE_MODE", "REALTIME"),
        allowed=ENGINE_MODES,
        allow_none=False,
    )

    raw_trade_mode = _get_env("TRADE_MODE", "SIMULATION")
    trade_mode = _validate_choice(
        name="TRADE_MODE",
        value=raw_trade_mode,
        allowed=TRADE_MODES,
        allow_none=True,
    )

    trading_state = _validate_choice(
        name="TRADING_STATE",
        value=_get_env("TRADING_STATE", "OFF"),
        allowed=TRADING_STATES,
        allow_none=False,
    )

    live_armed = _parse_bool(_get_env("LIVE_ARMED"), default=False)

    # BACKTEST 模式下，不使用 trade_mode，並強制 live_armed 為 False
    if engine_mode == "BACKTEST":
        trade_mode = None
        live_armed = False

    project_root = _project_root()
    env_file = _env_file_path()

    return Settings(
        app_env=app_env,
        db_host=db_host,
        db_port=db_port,
        db_name=db_name,
        db_user=db_user,
        db_password=db_password,
        binance_api_key=binance_api_key,
        binance_api_secret=binance_api_secret,
        primary_symbol=primary_symbol,
        primary_interval=primary_interval,
        engine_mode=engine_mode,
        trade_mode=trade_mode,
        trading_state=trading_state,
        live_armed=live_armed,
        project_root=project_root,
        env_file=env_file,
    )