import pytest

from manoj_bot.config import CostConfig, RiskConfig


@pytest.fixture
def no_costs() -> CostConfig:
    return CostConfig(fee_rate=0.0, slippage=0.0)


@pytest.fixture
def plain_risk() -> RiskConfig:
    """All-in sizing with no stops, so trades follow the signal only."""
    return RiskConfig(
        position_size=1.0, stop_loss=None, take_profit=None, max_drawdown=None, min_trade_value=0
    )
