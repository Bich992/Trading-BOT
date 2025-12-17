"""Centralized configuration using Pydantic for validation."""
from __future__ import annotations

import pathlib
from typing import List, Optional

from pydantic import BaseSettings, Field, validator


class AssetConfig(BaseSettings):
    symbol: str
    timeframes: List[str] = Field(default_factory=lambda: ["5m", "15m", "1h"])
    max_exposure_pct: float = Field(0.25, ge=0, le=1)


class PaperConfig(BaseSettings):
    starting_cash: float = Field(10_000.0, gt=0)
    fee_rate: float = Field(0.001, ge=0)
    slippage_bps: float = Field(1.5, ge=0)
    simulate_latency_ms: int = Field(120, ge=0)
    maker_fee: float = Field(0.0002, ge=0)
    taker_fee: float = Field(0.0006, ge=0)


class RiskConfig(BaseSettings):
    max_drawdown_pct: float = Field(0.2, ge=0, le=1)
    max_trades: int = Field(1000, ge=1)
    max_concurrent_legs: int = Field(6, ge=1)
    kill_switch_loss_pct: float = Field(0.25, ge=0, le=1)
    cooldown_seconds: int = Field(120, ge=0)
    allow_short: bool = True


class TuningConfig(BaseSettings):
    enable: bool = True
    interval_trades: int = Field(50, ge=1)
    grid_variation_pct: float = Field(0.1, ge=0)
    train_window: int = Field(300, ge=50)
    validation_window: int = Field(120, ge=30)
    objective: str = Field("sharpe", description="objective metric: sharpe|sortino|max_dd")
    storage_path: pathlib.Path = pathlib.Path("reports/best_params.json")


class EngineConfig(BaseSettings):
    python_version: str = Field("3.11")
    data_dir: pathlib.Path = pathlib.Path("data")
    reports_dir: pathlib.Path = pathlib.Path("reports")
    enable_live: bool = Field(False, description="Live trading requires explicit flag")
    assets: List[AssetConfig] = Field(default_factory=lambda: [AssetConfig(symbol="BTC/USDT")])
    paper: PaperConfig = PaperConfig()
    risk: RiskConfig = RiskConfig()
    tuning: TuningConfig = TuningConfig()

    @validator("reports_dir", "data_dir")
    def _ensure_dir(cls, v: pathlib.Path) -> pathlib.Path:
        v.mkdir(parents=True, exist_ok=True)
        return v

    @validator("enable_live")
    def _guard_live(cls, v: bool) -> bool:
        # Live must be explicitly set to True in config file.
        return bool(v)


DEFAULT_CONFIG = EngineConfig()


def load_config(path: Optional[pathlib.Path] = None) -> EngineConfig:
    if path is None:
        return DEFAULT_CONFIG
    return EngineConfig.parse_file(path)
