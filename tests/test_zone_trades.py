import pandas as pd
import pytest

from manoj_bot.cli import main
from manoj_bot.zone_trades import ZoneRules, stop_buffer, summarize, trades_frame, zone_trades
from manoj_bot.zones import Zone
from tests.helpers import make_bars
from tests.test_zones import RALLY_THEN_DROP

MONDAY = "2026-10-05 00:30"  # 06:00 in India
THURSDAY = "2026-10-08 00:30"
FLAT = (100.0, 100.5, 99.5, 100.0)  # open == close: never part of a pattern
C1 = (103.0, 103.5, 101.0, 101.5)
C2 = (101.3, 103.7, 100.5, 103.4)  # bullish engulfing: buy at 104.0, stop 100.0, 1R = 4
TO_1R = (103.5, 108.5, 103.2, 108.2)  # fills the buy and reaches 108 (1R)
TO_3R = (108.2, 116.5, 108.0, 116.0)
STOPPED = (103.5, 104.5, 99.5, 100.0)  # fills and hits the stop
B1 = (110.0, 114.0, 109.5, 113.5)
B2 = (
    113.0,
    114.5,
    112.0,
    112.5,
)  # bearish harami; its lowest point, 109.5, is 1.375R above the buy


def bars(rows, start=MONDAY):
    o, h, low, c = zip(*rows, strict=True)
    return make_bars(c, start=start, freq="15min", opens=o, highs=h, lows=low)


def broken(data, i, kind="resistance"):
    """A zone of ``kind`` that breaks on bar ``i``."""
    return Zone(kind, 90.0, 91.0, data.index[0], data.index[0], data.index[i], "broken")


def live(data, i, bottom, top, kind="resistance"):
    return Zone(kind, bottom, top, data.index[i], data.index[i])


def run(rows, zones=None, start=MONDAY, **rules):
    data = bars(rows, start)
    zones = [broken(data, 1)] if zones is None else zones(data)
    return zone_trades(data, ZoneRules(**rules), zones)


def test_buy_after_a_resistance_breaks_scales_out_at_1r_2r_3r():
    trades, setups = run([FLAT, FLAT, C1, C2, TO_1R, TO_3R])
    (trade,) = trades
    assert (trade.side, trade.pattern, trade.outcome) == ("buy", "bullish engulfing", "win")
    assert (trade.entry, trade.stop, trade.risk) == pytest.approx((104.0, 100.0, 4.0))
    assert trade.result_r == pytest.approx(2.0)  # a third each at 1R, 2R and 3R
    data = bars([FLAT] * 6)
    assert (trade.signal_time, trade.entry_time, trade.exit_time) == tuple(data.index[[3, 4, 5]])
    assert [s.status for s in setups] == ["traded"]


@pytest.mark.parametrize(
    ("after", "result", "outcome"),
    [
        ([STOPPED], -1.0, "loss"),
        ([TO_1R, (108.0, 108.3, 99.0, 99.5)], -1 / 3, "partial"),
        ([TO_1R, (108.2, 112.5, 108.0, 112.0), (112.0, 112.2, 107.0, 107.5)], 4 / 3, "trailed"),
        ([TO_1R], 1 / 3 + 2 / 3 * (108.2 - 104.0) / 4, "open"),
    ],
)
def test_outcomes(after, result, outcome):
    (trade,) = run([FLAT, FLAT, C1, C2, *after])[0]
    assert trade.outcome == outcome
    assert trade.result_r == pytest.approx(result)


def test_buy_aims_for_the_last_bearish_pattern_above():
    rows = [FLAT, B1, B2, FLAT, C1, C2, TO_1R, (108.2, 110.0, 108.0, 109.8)]
    (trade,) = run(rows)[0]
    assert (trade.outcome, trade.target) == ("target", 109.5)
    assert trade.result_r == pytest.approx((109.5 - 104.0) / 4)  # the whole trade closes there
    (stopped,) = run([FLAT, B1, B2, FLAT, C1, C2, STOPPED])[0]
    assert (stopped.outcome, stopped.result_r, stopped.target) == ("loss", -1.0, 109.5)
    (thirds,) = run(rows, opposite_target=False)[0]
    assert thirds.outcome == "open" and thirds.target is None


def test_an_opposite_pattern_3r_or_more_away_keeps_the_thirds():
    far1 = (116.5, 120.0, 116.0, 119.5)
    far2 = (119.0, 120.5, 118.0, 118.5)  # lowest point 116 is exactly 3R above the buy
    (trade,) = run([FLAT, far1, far2, FLAT, C1, C2, TO_1R, TO_3R])[0]
    assert (trade.outcome, trade.target) == ("win", None)
    assert trade.result_r == pytest.approx(2.0)


def test_rests_for_the_day_after_the_first_trade_wins():
    rows = [FLAT, FLAT, C1, C2, TO_1R, TO_3R, C1, C2, TO_1R, TO_3R]
    trades, setups = run(rows)
    assert len(trades) == 1 and setups[-1].status == "resting: first trade won"
    assert len(run(rows, rest_after_first_win=False)[0]) == 2


def test_thursday_allows_one_trade():
    rows = [FLAT, FLAT, C1, C2, STOPPED, C1, C2, TO_1R, TO_3R]
    assert len(run(rows)[0]) == 2  # Monday: the first trade lost, so it may trade again
    trades, setups = run(rows, start=THURSDAY)
    assert len(trades) == 1 and setups[-1].status == "daily trade limit"


def test_only_the_side_that_broke_today_is_open():
    rows = [FLAT, FLAT, C1, C2, TO_1R, TO_3R]
    trades, setups = run(rows, zones=lambda d: [broken(d, 1, "support")])
    assert trades == [] and setups[0].status == "side not open"
    assert run(rows, zones=lambda d: [])[1][0].status == "side not open"


def test_before_the_first_break_the_last_break_carries_over():
    # 05:00 in India: the resistance breaks at 05:15, before the trading day starts.
    early = "2026-10-04 23:30"
    rows = [FLAT, FLAT, C1, C2, FLAT, FLAT, C1, C2, TO_1R, TO_3R]
    trades, setups = run(rows, start=early)
    assert setups[0].status == "outside trading hours"
    assert len(trades) == 1 and trades[0].signal_time == bars(rows, early).index[7]
    # A support breaking at 06:00 opens only the sell side for the day.
    zones = lambda d: [broken(d, 1), broken(d, 4, "support")]  # noqa: E731
    assert run(rows, zones=zones, start=early)[1][-1].status == "side not open"


def test_a_candle_breaking_both_sides_carries_its_colour():
    early = "2026-10-04 23:30"
    rows = [FLAT, (100.0, 101.0, 99.0, 100.8), FLAT, FLAT, FLAT, FLAT, C1, C2, TO_1R, TO_3R]
    both = lambda d: [broken(d, 1), broken(d, 1, "support")]  # noqa: E731
    assert len(run(rows, zones=both, start=early)[0]) == 1  # green: the buy side carries
    rows[1] = (100.8, 101.0, 99.0, 100.0)
    assert run(rows, zones=both, start=early)[1][-1].status == "side not open"


def test_filters():
    rows = [FLAT, FLAT, C1, C2, TO_1R, TO_3R]
    assert run([FLAT, FLAT, C1, (101.3, 103.7, 88.0, 103.4), TO_1R])[1][0].status == (
        "stop too wide"
    )
    assert run([FLAT, FLAT, C1, C2, FLAT])[1][0].status == "not filled"
    # The 2nd candle is bar 6. A resistance 6 points above the entry is only 1.5R away;
    # 10 points is exactly 2.5R.
    later = [FLAT, FLAT, FLAT, FLAT, FLAT, C1, C2, TO_1R, TO_3R]
    near = lambda d: [broken(d, 1), live(d, 2, 110.0, 111.0)]  # noqa: E731
    assert run(later, zones=near)[1][0].status == "no room to the zone"
    far = lambda d: [broken(d, 1), live(d, 2, 114.0, 115.0)]  # noqa: E731
    assert len(run(later, zones=far)[0]) == 1
    young = lambda d: [broken(d, 1), live(d, 3, 110.0, 111.0)]  # noqa: E731
    assert len(run(later, zones=young)[0]) == 1  # under 4 candles old: ignored
    late = "2026-10-05 16:15"  # 21:45 in India: the 2nd candle closes at 22:00
    assert run(rows, start=late)[1][0].status == "outside trading hours"


def test_stop_buffer_grows_with_the_stop():
    assert [stop_buffer(p) for p in (3, 5, 7, 15, 25, 35, 45, 80)] == [
        0.5,
        0.5,
        1.0,
        1.5,
        2.0,
        3.0,
        4.0,
        5.0,
    ]


def test_bad_rules():
    with pytest.raises(ValueError, match="session"):
        ZoneRules(session_start=22, session_end=6)
    with pytest.raises(ValueError, match="max_stop"):
        ZoneRules(max_stop=0)
    with pytest.raises(ValueError, match="opposite_max_r"):
        ZoneRules(opposite_min_r=2, opposite_max_r=1)


def test_summary_and_frame():
    trades, _ = run([FLAT, FLAT, C1, C2, STOPPED, C1, C2, TO_1R, TO_3R])
    totals = summarize(trades)
    assert totals["trades"] == 2 and totals["wins"] == 1
    assert totals["net_r"] == pytest.approx(1.0) and totals["max_drawdown_r"] == pytest.approx(1.0)
    assert trades_frame(trades).outcome.tolist() == ["loss", "win"]
    assert summarize([])["trades"] == 0


def test_zone_trades_command(tmp_path, capsys):
    # The resistance in RALLY_THEN_DROP breaks on bar 8; then a bullish engulfing and a run to 3R.
    rows = [
        *RALLY_THEN_DROP,
        (110.5, 111.0, 108.5, 109.0),
        (108.8, 111.2, 108.0, 110.9),  # buy at 111.5, stop 107.5
        (111.0, 115.6, 110.8, 115.5),
        (115.5, 123.6, 115.3, 123.5),
    ]
    source, out, setups = tmp_path / "bars.csv", tmp_path / "trades.csv", tmp_path / "setups.csv"
    bars(rows).to_csv(source)
    args = ["zone-trades", "--csv", str(source), "-o", str(out), "--setups-out", str(setups)]
    assert main(args) == 0
    printed = capsys.readouterr().out
    assert "BUY   bullish engulfing" in printed and "win     +2.00R" in printed
    assert "Trades 1, win rate 100%, net +2.0R" in printed
    assert pd.read_csv(out).outcome.tolist() == ["win"]
    assert "traded" in pd.read_csv(setups).status.tolist()


def test_zone_trades_command_rejects_unknown_rules(tmp_path, capsys):
    source = tmp_path / "bars.csv"
    bars([FLAT] * 5).to_csv(source)
    assert main(["zone-trades", "--csv", str(source), "-p", "stop=3"]) == 1
    assert "Unknown rule" in capsys.readouterr().err
