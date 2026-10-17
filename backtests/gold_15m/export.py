"""Re-create trades.csv and monthly.csv: every backtest trade of the weak-zone rules on gold.

Usage (from the repo root, after `pip install -e .`):

    manoj-bot download --source dukascopy --symbol XAUUSD --timeframe 15m \\
        --start 2025-12-22 --end 2026-05-31 -o data/XAUUSD_15m_dec_may.csv
    manoj-bot download --source dukascopy --symbol XAUUSD --timeframe 15m \\
        --start 2026-06-01 --end 2026-10-16 -o data/XAUUSD_15m.csv
    python backtests/gold_15m/export.py

Each period is replayed on its own file (the week before Jan 1 only warms up the zones), with
the default ZoneRules. The account columns follow one $1,000 account through both periods,
risking 3% of the balance on every trade (the default LotRules).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from manoj_bot.lots import LotRules, replay_account
from manoj_bot.zone_trades import ZoneRules, summarize, zone_trades
from manoj_bot.zones import find_zones

IST = "Asia/Kolkata"
START_BALANCE = 1000.0
PERIODS = (  # label, bars file, first signal day (IST)
    ("Jan-May 2026", "data/XAUUSD_15m_dec_may.csv", "2026-01-01"),
    ("Jun-Oct 2026", "data/XAUUSD_15m.csv", "2026-06-01"),
)
OUT = Path(__file__).parent


def load(path: str) -> pd.DataFrame:
    bars = pd.read_csv(path, index_col=0)
    bars.index = pd.to_datetime(bars.index, utc=True)
    return bars


def main() -> None:
    trades, period = [], []
    for label, path, first in PERIODS:
        bars = load(path)
        found, _ = zone_trades(bars, ZoneRules(), find_zones(bars))
        found = [t for t in found if t.signal_time.tz_convert(IST) >= pd.Timestamp(first, tz=IST)]
        trades += found
        period += [label] * len(found)
        totals = summarize(found)
        print(
            f"{label}: {totals['trades']} trades, {totals['win_rate']:.0%} win, "
            f"{totals['net_r']:+.1f}R, worst drop {totals['max_drawdown_r']:.1f}R"
        )

    account = replay_account(trades, START_BALANCE, LotRules())

    def ist(ts: pd.Timestamp) -> str:
        return ts.tz_convert(IST).strftime("%Y-%m-%d %H:%M")

    rows = pd.DataFrame(
        {
            "period": period,
            "signal_time_ist": [ist(t.signal_time) for t in trades],
            "weekday": [t.signal_time.tz_convert(IST).strftime("%a") for t in trades],
            "side": [t.side for t in trades],
            "pattern": [t.pattern for t in trades],
            "entry_time_ist": [ist(t.entry_time) for t in trades],
            "entry": [round(t.entry, 2) for t in trades],
            "stop": [round(t.stop, 2) for t in trades],
            "risk_points": [round(t.risk, 2) for t in trades],
            "target": [None if t.target is None else round(t.target, 2) for t in trades],
            "exit_time_ist": [ist(t.exit_time) for t in trades],
            "outcome": [t.outcome for t in trades],
            "result_r": [round(t.result_r, 4) for t in trades],
            "lots": [a.lots for a in account],
            "pnl_usd": [round(a.pnl, 2) for a in account],
            "balance_usd": [round(a.balance_after, 2) for a in account],
        }
    )
    rows.to_csv(OUT / "trades.csv", index=False)

    peak, monthly = START_BALANCE, []
    rows["month"] = rows.signal_time_ist.str[:7]
    balance = START_BALANCE
    for month, g in rows.groupby("month", sort=True):
        start, drop = balance, 0.0
        for value in g.balance_usd:
            peak = max(peak, value)
            drop = max(drop, 1 - value / peak)
        balance = g.balance_usd.iloc[-1]
        monthly.append(
            {
                "month": month,
                "trades": len(g),
                "wins": int((g.result_r > 0).sum()),
                "losses": int((g.result_r <= 0).sum()),
                "net_r": round(g.result_r.sum(), 2),
                "pnl_usd": round(balance - start, 2),
                "pnl_pct": round(100 * (balance / start - 1), 1),
                "end_balance_usd": round(balance, 2),
                "worst_drop_pct": round(100 * drop, 1),
            }
        )
    pd.DataFrame(monthly).to_csv(OUT / "monthly.csv", index=False)
    print(f"{len(rows)} trades; ${START_BALANCE:,.0f} -> ${balance:,.2f} at 3% compounding")


if __name__ == "__main__":
    main()
