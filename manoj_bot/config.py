"""Bot configuration, loaded from a YAML file (see ``config.example.yaml``)."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from manoj_bot.timeframes import parse_timeframe

MODES = ("paper", "live")
DATA_SOURCES = ("synthetic", "csv", "yahoo", "ccxt", "dukascopy")


@dataclass
class DataConfig:
    source: str = "synthetic"  # synthetic | csv | yahoo | ccxt | dukascopy
    exchange: str = "binance"  # ccxt exchange id used for market data
    path: str | None = None  # CSV file, for source "csv"
    seed: int = 42  # random seed, for source "synthetic"


@dataclass
class StrategyConfig:
    name: str = "ma_crossover"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskConfig:
    position_size: float = 0.95  # max fraction of equity put into one position
    risk_per_trade: float | None = None  # fraction of equity lost if the stop is hit
    stop_loss: float | None = 0.05  # exit when price falls this fraction below entry
    take_profit: float | None = None  # exit when price rises this fraction above entry
    max_drawdown: float | None = 0.25  # stop trading when equity falls this far below its peak
    min_trade_value: float = 10.0  # skip orders (and treat positions) smaller than this
    lot_size: float | None = None  # round quantities down to a multiple of this (1 = whole shares)


@dataclass
class CostConfig:
    fee_rate: float = 0.001  # commission per fill, as a fraction of traded value
    slippage: float = 0.0005  # assumed adverse price move per fill


@dataclass
class BrokerConfig:
    exchange: str = "binance"  # ccxt exchange id used for live orders
    sandbox: bool = True  # trade on the exchange's testnet


@dataclass
class BotConfig:
    mode: str = "paper"  # paper | live
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    capital: float = 1000.0  # quote currency the bot is allowed to trade with
    poll_interval: float = 60.0  # seconds between checks when running
    state_file: str = "state/bot_state.json"
    data: DataConfig = field(default_factory=DataConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    costs: CostConfig = field(default_factory=CostConfig)
    broker: BrokerConfig = field(default_factory=BrokerConfig)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> BotConfig:
        raw = dict(raw or {})
        sections = {
            name: _build(section, raw.pop(name) or {}, name)
            for name, section in _SECTIONS.items()
            if name in raw
        }
        config = _build(cls, {**raw, **sections}, "top-level")
        config.validate()
        return config

    @classmethod
    def load(cls, path: str | Path) -> BotConfig:
        return cls.from_dict(yaml.safe_load(Path(path).read_text()))

    def validate(self) -> None:
        _check(self.mode in MODES, f"mode must be one of {MODES}, got {self.mode!r}")
        _check(isinstance(self.symbol, str) and bool(self.symbol), "symbol must be set")
        parse_timeframe(self.timeframe)
        _check(_number(self.capital) and self.capital > 0, "capital must be > 0")
        _check(_number(self.poll_interval) and self.poll_interval > 0, "poll_interval must be > 0")

        _check(
            self.data.source in DATA_SOURCES,
            f"data.source must be one of {DATA_SOURCES}, got {self.data.source!r}",
        )
        _check(
            self.data.source != "csv" or bool(self.data.path), "data.source 'csv' needs data.path"
        )
        _check(isinstance(self.strategy.params, dict), "strategy.params must be a mapping")

        risk = self.risk
        _check(
            _number(risk.position_size) and 0 < risk.position_size <= 1,
            "risk.position_size must be in (0, 1]",
        )
        for name in ("risk_per_trade", "stop_loss", "max_drawdown"):
            value = getattr(risk, name)
            _check(
                value is None or (_number(value) and 0 < value < 1),
                f"risk.{name} must be in (0, 1)",
            )
        _check(
            risk.take_profit is None or (_number(risk.take_profit) and risk.take_profit > 0),
            "risk.take_profit must be > 0",
        )
        _check(
            risk.risk_per_trade is None or risk.stop_loss is not None,
            "risk.risk_per_trade needs risk.stop_loss",
        )
        _check(
            _number(risk.min_trade_value) and risk.min_trade_value >= 0,
            "risk.min_trade_value must be >= 0",
        )
        _check(
            risk.lot_size is None or (_number(risk.lot_size) and risk.lot_size > 0),
            "risk.lot_size must be > 0",
        )
        for name in ("fee_rate", "slippage"):
            value = getattr(self.costs, name)
            _check(_number(value) and 0 <= value < 1, f"costs.{name} must be in [0, 1)")


_SECTIONS = {
    "data": DataConfig,
    "strategy": StrategyConfig,
    "risk": RiskConfig,
    "costs": CostConfig,
    "broker": BrokerConfig,
}


def _build(cls, raw: Any, where: str):
    if not isinstance(raw, dict):
        raise ValueError(f"{where} config must be a mapping")
    allowed = {f.name for f in dataclasses.fields(cls)}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(
            f"Unknown {where} option(s): {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(allowed))}"
        )
    return cls(**raw)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)
