# Optional integrations (not used yet)

Two outside services were looked at for Manoj-Bot. Neither is wired into the bot; use them
when there is a concrete need.

## Roboquant: US futures platform

- **What it is:** a hosted platform (roboquant.dev) for writing strategies in its own `.rq`
  language, backtesting them on CME data (bars, ticks, order book), optimising parameters,
  and running them 24x7 through the Tradovate broker.
- **Status:** connected to Claude as a connector on claude.ai. It can create and edit
  strategies, run backtests and optimisations, and read results. It can only *read* live
  deployments; starting or stopping them stays manual.
- **Limits:**
  - CME futures only (equity index, rates, FX, livestock, crypto futures). No NSE/BSE
    stocks and no spot crypto.
  - Raw price data cannot be exported (it is licensed CME data); only your own results
    (metrics, trades, equity curves, charts, live logs) are available.
  - Free plan: 5 backtests a day. Their site lists AI/MCP access on the Elite plan
    ($149/month).
- **Good for:** realistic intraday futures testing and always-on futures bots.
- **Free alternative for futures prices in Manoj-Bot:** Yahoo tickers such as `ES=F`,
  `NQ=F`, `GC=F`, `CL=F`, `BTC=F`, for example
  `manoj-bot backtest --source yahoo --symbol ES=F --timeframe 1d --start 2022-01-01`.

## Jev by TypeSafe: fast AI decisions

- **What it is:** an AI model (typesafe.ai) that returns typed decisions with probabilities
  instead of text: Choice (pick one option), Score (rate on a scale) and Noul (yes/no
  probability). It is in early access.
- **Idea for the bot:** an optional news filter. When a buy signal fires, send the latest
  headlines for the symbol in one call and ask how bullish or bearish they are, whether a
  major negative event is mentioned, and whether the news is really about this company.
  Skip the buy when the news is clearly bearish. Test it with paper trading first.
- **To enable:**
  - Get an API key at console.typesafe.ai/keys and store it as the `TYPESAFE_API_KEY`
    secret or environment variable (never in a file in this repo).
  - Python SDK: `pip install typesafe-sdk`; HTTP endpoint
    `POST https://api.typesafe.ai/v1/systemone`; model `jev-latest`.
  - Agent skill for Claude Code: `claude plugin marketplace add typesafe-ai/skills`, then
    `claude plugin install typesafe@typesafe-ai`.
- **Keeping token costs low** (only input tokens are billed):
  - Ask all questions about the same headlines in one call; the text is billed once.
  - Send headlines or short summaries, not full articles.
  - Cache answers, and only call when a buy signal fires, not on every market check.
- **Docs:** https://docs.typesafe.ai/llms.txt
