import pandas as pd

from manoj_bot.cli import main
from manoj_bot.zones import find_zones, zones_frame
from tests.helpers import make_bars


def bars(rows):
    """Bars from (open, high, low, close) rows."""
    o, h, low, c = zip(*rows, strict=True)
    return make_bars(c, opens=o, highs=h, lows=low, freq="15min")


# A rally of 3+ green candles, a top at bar 4, then 3 red candles and a candle through the top.
RALLY_THEN_DROP = [
    (100.0, 101.0, 99.0, 100.5),
    (100.5, 103.0, 100.0, 102.5),
    (102.5, 106.0, 102.0, 105.5),  # 3rd green with higher highs: support formed
    (105.5, 108.0, 105.0, 107.5),  # 4th green: a second support would not alternate
    (107.5, 110.0, 107.0, 109.0),  # top of the move
    (109.0, 109.5, 106.0, 106.5),
    (106.5, 107.0, 104.0, 104.5),
    (104.5, 105.0, 102.5, 103.0),  # 3rd red with lower lows: resistance formed
    (103.0, 111.0, 102.8, 110.5),  # wick through the resistance
]


def test_support_then_resistance_anchored_on_the_previous_high():
    data = bars(RALLY_THEN_DROP)
    support, resistance = find_zones(data)

    assert support.kind == "support" and support.is_support
    assert (support.bottom, support.top) == (99.0, 100.0)  # lowest low -> lowest body
    assert support.start == data.index[0] and support.formed == data.index[2]
    assert support.end is None

    assert resistance.kind == "resistance"
    assert (resistance.bottom, resistance.top) == (109.0, 110.0)  # highest body -> highest high
    assert resistance.start == data.index[4] and resistance.formed == data.index[7]
    assert resistance.end == data.index[8] and resistance.end_reason == "broken"


def test_previous_high_counts_from_the_last_support_not_an_older_high():
    data = bars(
        [
            (110.0, 120.0, 109.0, 111.0),  # an old, higher high
            (111.0, 111.5, 105.0, 105.5),
            (105.5, 106.0, 101.0, 101.5),
            (101.5, 102.0, 98.0, 98.5),  # 3 red: first resistance
            (98.5, 100.0, 98.2, 99.5),
            (99.5, 102.0, 99.0, 101.5),
            (101.5, 104.0, 101.0, 103.5),  # 3 green: support
            (103.5, 108.0, 103.0, 107.5),  # the previous high
            (107.5, 107.8, 105.0, 105.5),
            (105.5, 106.0, 103.5, 104.0),
            (104.0, 104.5, 102.0, 102.5),  # 3 red: second resistance
        ]
    )
    first, support, second = find_zones(data)
    assert support.kind == "support" and support.start == data.index[3]
    assert (second.bottom, second.top) == (107.5, 108.0)
    assert second.start == data.index[7]
    # Only the newest resistance is kept.
    assert first.end == data.index[10] and first.end_reason == "replaced"
    assert second.end is None


def test_zones_expire():
    data = bars(RALLY_THEN_DROP)
    support = find_zones(data, max_age=3)[0]
    assert support.end == data.index[5] and support.end_reason == "expired"


def test_zones_never_use_later_candles():
    data = bars(RALLY_THEN_DROP)
    early = find_zones(data.iloc[:8])
    full = find_zones(data)
    assert [(z.kind, z.bottom, z.top, z.start) for z in early] == [
        (z.kind, z.bottom, z.top, z.start) for z in full
    ]


def test_zones_frame_has_one_row_per_zone():
    frame = zones_frame(find_zones(bars(RALLY_THEN_DROP)))
    assert frame.kind.tolist() == ["support", "resistance"]
    assert frame.end_reason.tolist()[1] == "broken"
    assert pd.isna(frame.end.iloc[0])


def test_zones_command(tmp_path, capsys):
    source, out = tmp_path / "bars.csv", tmp_path / "zones.csv"
    bars(RALLY_THEN_DROP).to_csv(source)
    args = ["zones", "--csv", str(source), "--tz", "Asia/Kolkata", "-o", str(out)]
    assert main(args) == 0
    printed = capsys.readouterr().out
    assert "2 weak zones" in printed
    assert "resistance  109.00 - 110.00" in printed and "broken" in printed
    assert pd.read_csv(out).kind.tolist() == ["support", "resistance"]


def test_zones_command_rejects_bad_timeframe(tmp_path, capsys):
    source = tmp_path / "bars.csv"
    bars(RALLY_THEN_DROP).to_csv(source)
    assert main(["zones", "--csv", str(source), "--timeframe", "7x"]) == 1
    assert "error" in capsys.readouterr().err
