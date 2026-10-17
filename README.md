# Manoj-Bot

A modular trading bot written in Python. You can:

1. **Backtest** strategies on historical data: stocks (including NSE/BSE), crypto or your own CSV files.
2. **Paper trade** them on live prices with simulated orders. This is the default.
3. **Trade live** on 100+ crypto exchanges through [ccxt](https://github.com/ccxt/ccxt), once you have opted in.

> **Disclaimer:** this is educational software, not financial advice. Trading can lose money,
> and a good backtest does not mean future profits. Start with backtests, then paper trading,
> then an exchange testnet, and only risk money you can afford to lose.

## Features

- **Realistic backtests:** a signal fires on a bar's close and is filled at the next bar's open. Stop-loss and take-profit trigger inside the bar, and price gaps are handled. Fees and slippage are charged on every fill.
- **Reports:** total return vs. buy & hold, CAGR, Sharpe ratio, max drawdown, win rate, profit factor, time in market and fees paid. Trades and the equity curve can be exported to CSV.
- **Data sources:** Yahoo Finance (stocks, ETFs, indices; `RELIANCE.NS`, `TCS.BO`, `^NSEI`, `AAPL`), any ccxt crypto exchange, Dukascopy (spot gold, silver and FX), CSV files, or synthetic prices for offline experiments. `manoj-bot download` saves any of them to CSV.
- **Strategies:** moving-average crossover (SMA or EMA) and RSI mean reversion with an optional trend filter. Adding your own takes about 20 lines.
- **Risk management:** position sizing by share of equity or by risk per trade, stop-loss, take-profit, a max-drawdown kill switch, and whole-share or lot sizes.
- **Safe defaults:**
  - Paper mode unless you choose otherwise.
  - Live mode needs both `mode: live` and `--confirm-live`, and uses the testnet by default.
  - API keys come only from environment variables.
  - The bot trades only the `capital` you assign it.
- **Restart-safe:** the bot keeps its own ledger (cash, position, trades) in a JSON state file.

## Install

Requires Python 3.10+.

```bash
git clone https://github.com/RGCbe/Manoj-Bot.git
cd Manoj-Bot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"   # or ".[stocks]" (Yahoo only) / ".[crypto]" (ccxt only)
```

## Quick start

### 1. Backtest

```bash
# Offline demo on synthetic prices (no internet needed)
manoj-bot backtest

# Reliance Industries on NSE, daily bars
manoj-bot backtest --source yahoo --symbol RELIANCE.NS --timeframe 1d --start 2019-01-01

# NIFTY 50, hourly bars, RSI strategy with custom parameters
manoj-bot backtest --source yahoo --symbol ^NSEI --timeframe 1h --bars 500 \
    --strategy rsi_reversion -p oversold=25 -p exit_level=60

# Bitcoin on Binance, 4-hour bars, EMA crossover, export the trades
manoj-bot backtest --source ccxt --exchange binance --symbol BTC/USDT --timeframe 4h \
    --start 2023-01-01 -p fast=12 -p slow=26 -p kind=ema --trades-out trades.csv

# Spot gold (XAU/USD) from Dukascopy, 15-minute bars
manoj-bot backtest --source dukascopy --symbol XAUUSD --timeframe 15m --start 2026-06-01

# Your own data (columns: date/timestamp, open, high, low, close[, volume])
manoj-bot backtest --csv data/prices.csv --timeframe 1d

# Use every setting from a config file
manoj-bot backtest -c config.yaml
```

Example output:

```
Symbol             RELIANCE.NS 1d via yahoo
Strategy           MaCrossover(fast=20, slow=50, kind='sma')
Period             2019-01-01 18:30 -> 2025-12-30 18:30
Bars               1729
Initial capital    1,000.00
Final equity       1,364.99
Total return       36.50%
Buy & hold return  219.19%
CAGR               4.55%
Sharpe ratio       0.44
Max drawdown       -26.15%
Trades             9
Win rate           44.44%
Profit factor      2.21
Avg trade return   4.55%
Time in market     17.35%
Fees paid          22.57
```

In this run the default strategy lost to buy & hold. That is common, and it is why you
backtest before trading. Times are shown in UTC.

`manoj-bot strategies` lists the strategies and their parameters.

### Saving data to CSV

`manoj-bot download` saves bars from any source to a CSV file. You can then re-run
backtests offline on exactly the same data with `--csv`:

```bash
manoj-bot download --source dukascopy --symbol XAUUSD --timeframe 15m --start 2026-06-01 \
    -o data/XAUUSD_15m.csv
manoj-bot backtest --csv data/XAUUSD_15m.csv --timeframe 15m
```

About Dukascopy:
- It is free, needs no API key, and gives real spot prices: the mid of bid and ask, close
  to what TradingView shows for spot gold.
- It is slow and often throttles requests, so expect about 3 days of data per minute.
- Completed days are cached in `~/.cache/manoj-bot/dukascopy`, so an interrupted
  download resumes where it stopped.
- The `data/` folder is git-ignored. Re-create its files with `manoj-bot download`
  instead of committing them.

### Weak zones (support and resistance)

`manoj-bot zones` lists the weak zones the way they are marked by hand on a 15-minute
gold chart. The rules are written out at the top of `manoj_bot/zones.py`:

- **Formation:** 3 same-colour candles, each breaking the one before.
- **Anchor:** each zone starts at the previous high or low.
- **Alternation:** zones alternate between support and resistance.
- **Newest only:** a new zone replaces the old one of its kind.
- **End:** a zone dies when a wick breaks through it, or after 2 days.

Checked against the mentor's chart photos from Sep 25 to Oct 16, it draws almost all of
his zones.

```bash
manoj-bot zones --csv data/XAUUSD_15m.csv --start 2026-10-15 --tz Asia/Kolkata
manoj-bot zones --source dukascopy --symbol XAUUSD --start 2026-10-15 -o zones.csv
```

### Weak-zone trades (the mentor's entry rules)

`manoj-bot zone-trades` replays the mentor's trading rules on top of the weak zones and
reports every trade in R (1R = the distance from entry to stop). The full rules are at
the top of `manoj_bot/zone_trades.py`. Times are India time.

- **Direction:** from 06:00, the first resistance that breaks opens buys and the first
  support that breaks opens sells. Before any break that day, the last break carries over.
- **Entry:** a bullish or bearish engulfing or harami. Buy stop 0.3 above the 2nd candle
  (sell stop 0.3 below), filled only by the next candle. The stop-loss goes beyond the two
  candles plus a buffer.
- **Room:** the zone in the way (resistance for a buy, support for a sell) must be broken
  or at least 2.5R away.
- **Filters:** 06:00-22:00 only, stop at most 15 points, one trade at a time, at most 3
  trades a day and 1 on Thursday. After a winning first trade the bot stops for the day.
- **Exit:** a third at 1R, 2R and 3R; after 2R the stop moves to 1R.

```bash
manoj-bot zone-trades --csv data/XAUUSD_15m.csv --start 2026-06-01
manoj-bot zone-trades --source dukascopy --start 2026-10-01 -o trades.csv
manoj-bot zone-trades --csv data/XAUUSD_15m.csv -p max_trades_thursday=3 --setups-out setups.csv
```

`-p` changes any rule. `--setups-out` lists every pattern with the reason it was or was
not traded. Start a few days before the period you care about, so the first zones and
breaks already exist.

On spot gold from Jun 1 to Oct 16 2026 this gave 166 trades, a 43% win rate and +45.3R
in total. The worst drop was 12.3R, and every month was positive. The rules were tuned
on those same months, so test them on other dates before trusting them. The command
only backtests for now; paper and live trading do not use these rules yet.

### 2. Paper trade

```bash
cp config.example.yaml config.yaml   # then edit config.yaml
manoj-bot run                        # checks the market every poll_interval seconds; Ctrl+C stops it
manoj-bot run --once                 # one check, handy for cron jobs
manoj-bot status                     # cash, open position and recent trades
```

Example `config.yaml` for an NSE stock:

```yaml
mode: paper
symbol: RELIANCE.NS
timeframe: 15m
capital: 100000          # INR
state_file: state/reliance.json
data:
  source: yahoo
strategy:
  name: ma_crossover
  params: {fast: 20, slow: 50}
risk:
  stop_loss: 0.03
  lot_size: 1            # whole shares only
```

Yahoo Finance data can be delayed by about 15 minutes. That is fine for paper trading but
not for live trading.

### 3. Live trading (crypto via ccxt)

1. Create API keys on your exchange's **testnet** first (for example the Binance Spot Testnet). Allow trading but **not withdrawals**.
2. Export the keys. They are never read from the config file:
   ```bash
   export MANOJ_BOT_API_KEY=...
   export MANOJ_BOT_API_SECRET=...
   export MANOJ_BOT_API_PASSWORD=...   # only for exchanges that need a passphrase (OKX, KuCoin)
   ```
3. In `config.yaml`, set `mode: live`, `data.source: ccxt`, and the same exchange under `data.exchange` and `broker.exchange`.
4. Run `manoj-bot run --confirm-live`.

With `broker.sandbox: true` (the default) orders go to the testnet. Set it to `false` only
when you are ready to use real money.

Things to know about live trading:

- **Spot only, long only:** the bot buys, then sells what it bought.
- **Capital:** it trades only the `capital` you set, tracked in its own ledger. Other coins in your account are left alone.
- **Stops:** stop-loss and take-profit are checked on every poll; they are not orders resting on the exchange. **If the bot is not running, stops are not enforced.**
- **Drawdown halt:** after the max-drawdown limit is hit the bot sells and stops trading. Delete the state file to reset it.

## How it works

```
data feed ──► strategy ──► signal (1 = long, 0 = flat) ──► risk rules ──► broker
 (Yahoo,       (closed bars                                  (size, stop,    (paper or
  ccxt, CSV)    only)                                         drawdown)       ccxt)
```

- A **strategy** looks at OHLCV bars and returns a target position for every bar. It only sees bars that have closed, so it cannot peek at the future (the tests check this).
- The **backtester** (`manoj_bot/backtest.py`) replays history bar by bar:
  - A signal from a bar's close is filled at the next bar's open.
  - Stops and targets are checked against each bar's low and high. A bar that gaps past one exits at the open, and when both fall inside one bar the stop is assumed to hit first.
  - After a stop-loss or take-profit exit, the strategy must go flat before the bot buys again.
- The **live engine** (`manoj_bot/engine.py`) runs the same logic on each poll against the latest price, then saves its state.

## Configuration

See [`config.example.yaml`](config.example.yaml) for a commented example.

| Key | Default | Meaning |
| --- | --- | --- |
| `mode` | `paper` | `paper` (simulated) or `live` (real orders via ccxt) |
| `symbol` | `BTC/USDT` | Market to trade, e.g. `BTC/USDT`, `RELIANCE.NS`, `AAPL` |
| `timeframe` | `1h` | Bar size: `1m` `5m` `15m` `30m` `1h` `4h` `1d` `1w` |
| `capital` | `1000` | Amount of quote currency the bot may use |
| `poll_interval` | `60` | Seconds between market checks in `run` |
| `state_file` | `state/bot_state.json` | Where the bot's ledger is saved (one per symbol) |
| `data.source` | `synthetic` | `synthetic`, `csv`, `yahoo`, `ccxt` or `dukascopy` |
| `data.exchange` | `binance` | ccxt exchange for market data |
| `data.path` | | CSV file, for `source: csv` |
| `strategy.name` / `strategy.params` | `ma_crossover` | See `manoj-bot strategies` |
| `risk.position_size` | `0.95` | Largest share of equity in one position |
| `risk.risk_per_trade` | off | Size positions so that hitting the stop loses this share of equity |
| `risk.stop_loss` | `0.05` | Sell 5% below entry |
| `risk.take_profit` | off | Sell this far above entry |
| `risk.max_drawdown` | `0.25` | Stop trading after a 25% fall from peak equity |
| `risk.min_trade_value` | `10` | Skip smaller orders |
| `risk.lot_size` | off | Round quantities down to multiples of this; `1` = whole shares |
| `costs.fee_rate` / `costs.slippage` | `0.001` / `0.0005` | Simulated costs per fill |
| `broker.exchange` / `broker.sandbox` | `binance` / `true` | Exchange for live orders, and whether to use its testnet |

## Adding a strategy

Create `manoj_bot/strategies/my_strategy.py`:

```python
from dataclasses import dataclass
from typing import ClassVar

from manoj_bot.strategies.base import Strategy


@dataclass
class Breakout(Strategy):
    """Long while the close is above its highest close of the last `window` bars."""

    name: ClassVar[str] = "breakout"
    window: int = 20

    @property
    def warmup(self) -> int:
        return self.window + 1

    def generate_signals(self, data):
        prior_high = data["close"].rolling(self.window).max().shift(1)
        return (data["close"] > prior_high).astype(int)
```

Then add it to the `STRATEGIES` registry in `manoj_bot/strategies/__init__.py`. After that
`manoj-bot backtest --strategy breakout -p window=55` works, as does using it from a config file.

## Project layout

```
manoj_bot/
  cli.py            command line (backtest, run, status, strategies, download, zones,
                    zone-trades)
  config.py         YAML config and validation
  backtest.py       bar-by-bar backtester
  engine.py         paper/live trading loop and state file
  metrics.py        performance statistics
  risk.py           position sizing, stop/target levels, drawdown check
  portfolio.py      cash/position ledger, fills and trades
  indicators.py     SMA, EMA, RSI
  zones.py          weak zones (support / resistance)
  zone_trades.py    the mentor's entry and exit rules on the weak zones
  strategies/       ma_crossover, rsi_reversion
  data/             yahoo, ccxt, csv and synthetic feeds
  brokers/          paper and ccxt brokers
tests/              pytest suite (runs offline)
```

## Development

```bash
pip install -e ".[dev]"
pytest            # the whole suite runs offline, using fake exchanges and feeds
ruff check . && ruff format --check .
```

## Ideas for next steps

- Live trading for Indian stocks through a broker API (Zerodha Kite Connect, Upstox, Angel One SmartAPI). This means adding a `Broker` implementation.
- Telegram or email alerts for trades.
- Parameter optimisation and walk-forward testing.
- Short selling and futures.
- Equity-curve charts.
