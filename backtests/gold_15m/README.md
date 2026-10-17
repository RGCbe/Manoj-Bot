# Gold backtest: every weak-zone trade, Jan - Oct 2026

All 313 trades the weak-zone rules (`manoj_bot/zone_trades.py`, default `ZoneRules`) take on
spot gold, 15-minute candles from Dukascopy (mid of bid and ask). Times are India time.

| File | What it holds |
|---|---|
| `trades.csv` | One row per trade: time, side, pattern, entry, stop, 1R in points, the opposite-pattern target if one was used, exit, outcome, result in R, and a $1,000 account risking 3% a trade (lots, P&L, balance) |
| `monthly.csv` | Trades, wins, losses, R, P&L, the balance and the worst drop from the top, per month |
| `export.py` | Re-creates both files (the commands are at the top of the script) |

## Results

| Period | Trades | Win rate | Net | Worst drop |
|---|---|---|---|---|
| Jan - May 2026 | 147 | 39% | +22.7R | 9.9R |
| Jun - Oct 16 2026 | 166 | 43% | +46.3R | 12.5R |

A $1,000 account risking 3% of its balance on every trade (0.01-lot steps, 100 oz a lot)
ends Jan - Oct at **$4,842**. Its worst drop from the top was 30.8%, in September.

Outcomes: `win` (all thirds to 3R), `trailed` (2R, then back to the 1R stop), `partial` (1R,
then the stop), `target` (closed at the opposite pattern), `loss`.

## Read before trusting it

- **Tuned period:** the entry and day rules were tuned on Jun - Oct. Jan - May was kept back
  to check them, but the opposite-pattern exit was chosen after seeing both periods.
- **Costs:** only a 0.2-point spread is counted, inside the entry price. There is no
  commission, swap or slippage. Delta Exchange (XAUTUSD) costs about 1 point a trade.
- **Fills:** a candle that touches both the stop and a target counts as a stop.
- **Backtest only:** this is not live trading. Paper trade before risking money.
