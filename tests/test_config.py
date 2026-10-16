from pathlib import Path

import pytest

from manoj_bot.config import BotConfig

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.yaml"


def test_example_config_loads():
    config = BotConfig.load(EXAMPLE)
    assert config.mode == "paper"
    assert config.data.source == "ccxt"
    assert config.strategy.params == {"fast": 20, "slow": 50, "kind": "sma"}
    assert config.broker.sandbox is True


def test_defaults_and_empty_sections():
    config = BotConfig.from_dict({"risk": None, "costs": {"fee_rate": 0}})
    assert config.risk.stop_loss == 0.05
    assert config.costs.fee_rate == 0
    assert BotConfig.from_dict(None) == BotConfig()


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"colour": "red"}, "Unknown top-level option"),
        ({"risk": {"stop": 0.1}}, "Unknown risk option"),
        ({"risk": [1]}, "must be a mapping"),
        ({"mode": "yolo"}, "mode"),
        ({"capital": 0}, "capital"),
        ({"timeframe": "1x"}, "timeframe"),
        ({"data": {"source": "csv"}}, "data.path"),
        ({"data": {"source": "bloomberg"}}, "data.source"),
        ({"risk": {"stop_loss": 1.5}}, "stop_loss"),
        ({"risk": {"position_size": 0}}, "position_size"),
        ({"risk": {"risk_per_trade": 0.01, "stop_loss": None}}, "needs risk.stop_loss"),
        ({"risk": {"lot_size": 0}}, "lot_size"),
        ({"costs": {"fee_rate": -1}}, "fee_rate"),
    ],
)
def test_invalid_config(raw, message):
    with pytest.raises(ValueError, match=message):
        BotConfig.from_dict(raw)
