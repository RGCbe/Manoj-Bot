import pandas as pd
import pytest

from manoj_bot.cli import main
from manoj_bot.lots import LotRules, lot_size, replay_account, split_thirds, trade_pnl
from manoj_bot.zone_trades import ZoneTrade
from tests.test_zone_trades import bars
from tests.test_zones import RALLY_THEN_DROP

T = pd.Timestamp("2026-10-05 01:00", tz="UTC")


def trade(outcome, result_r, risk=10.0, entry=4000.0):
    return ZoneTrade(
        "buy", "bullish engulfing", T, T, entry, entry - risk, risk, T, result_r, outcome
    )


def test_lot_size_risks_at_most_the_share_of_the_balance():
    rules = LotRules(risk=0.02)
    assert lot_size(1000, 4000, 3990, rules) == pytest.approx(0.02)  # $20 / (10 points x 100 oz)
    assert lot_size(1000, 4000, 3992, rules) == pytest.approx(0.02)  # 0.025 rounds down
    assert lot_size(3000, 4000, 4010, rules) == pytest.approx(0.06)  # sells too
    assert lot_size(100, 4000, 3990, rules) == 0.0  # 0.002 lots: below the 0.01 minimum


def test_lot_size_caps_and_costs():
    assert lot_size(1_000_000, 4000, 3990, LotRules(risk=0.02, max_lot=5)) == 5.0
    # 1:10 leverage: $1,000 holds at most 0.025 lots of 100 oz at $4,000
    assert lot_size(1000, 4000, 3990, LotRules(risk=0.5, leverage=10)) == pytest.approx(0.02)
    # $7 commission a lot: $20 / $1,007 per lot rounds down to 0.01
    assert lot_size(1000, 4000, 3990, LotRules(risk=0.02, commission_per_lot=7)) == 0.01


def test_split_thirds_in_whole_lot_steps():
    assert split_thirds(0.02, 0.01) == (0.01, 0.01, 0.0)
    assert split_thirds(0.03, 0.01) == (0.01, 0.01, 0.01)
    assert split_thirds(0.05, 0.01) == (0.02, 0.02, 0.01)
    assert split_thirds(0.10, 0.01) == (0.04, 0.03, 0.03)


@pytest.mark.parametrize(
    ("outcome", "result_r", "lots", "pnl"),
    [
        ("loss", -1.0, 0.03, -30.0),
        ("partial", -1 / 3, 0.03, -10.0),
        ("partial", -1 / 3, 0.02, 0.0),  # 0.01 closed at +1R, 0.01 stopped at -1R
        ("win", 2.0, 0.03, 60.0),
        ("win", 2.0, 0.02, 30.0),  # nothing left for 3R
        ("trailed", 4 / 3, 0.03, 40.0),
        ("target", 1.5, 0.02, 30.0),
    ],
)
def test_trade_pnl(outcome, result_r, lots, pnl):
    # 10-point stop: 1R is $1,000 a lot
    assert trade_pnl(trade(outcome, result_r), lots, LotRules()) == pytest.approx(pnl)


def test_commission_is_charged_per_lot():
    assert trade_pnl(trade("loss", -1.0), 0.02, LotRules(commission_per_lot=7)) == pytest.approx(
        -20.14
    )


def test_replay_account_sizes_from_the_current_balance():
    rows = replay_account(
        [trade("loss", -1.0), trade("win", 2.0), trade("loss", -1.0)], 3000, LotRules(risk=0.02)
    )
    assert [r.lots for r in rows] == pytest.approx([0.06, 0.05, 0.06])
    # 0.05 lots split 0.02 / 0.02 / 0.01, so the win pays 0.09 x $1,000
    assert [r.pnl for r in rows] == pytest.approx([-60.0, 90.0, -60.0])
    assert rows[-1].balance_after == pytest.approx(2970.0)
    assert rows[0].risk_money == pytest.approx(60.0)
    skipped = replay_account([trade("win", 2.0)], 100, LotRules(risk=0.02))[0]
    assert (skipped.lots, skipped.pnl, skipped.balance_after) == (0.0, 0.0, 100.0)


def test_bad_lot_rules():
    with pytest.raises(ValueError, match="risk"):
        LotRules(risk=2)
    with pytest.raises(ValueError, match="lot_step"):
        LotRules(lot_step=0)


def test_zone_trades_command_with_a_balance(tmp_path, capsys):
    rows = [
        *RALLY_THEN_DROP,
        (110.5, 111.0, 108.5, 109.0),
        (108.8, 111.2, 108.0, 110.9),  # buy at 111.5, stop 107.5: 1R = 4 points
        (111.0, 115.6, 110.8, 115.5),
        (115.5, 123.6, 115.3, 123.5),
    ]
    source, out = tmp_path / "bars.csv", tmp_path / "trades.csv"
    bars(rows).to_csv(source)
    args = ["zone-trades", "--csv", str(source), "--balance", "1000", "--risk", "0.02"]
    assert main([*args, "-o", str(out)]) == 0
    printed = capsys.readouterr().out
    # $20 / (4 points x 100 oz) = 0.05 lots: 0.02 at 1R, 0.02 at 2R, 0.01 at 3R = 0.09 x $400
    assert "0.05 lot +36.00 -> 1,036.00" in printed
    assert "Account 1,000.00 -> 1,036.00 (+3.6%) risking 2.0% a trade" in printed
    assert pd.read_csv(out).lots.tolist() == [0.05]
