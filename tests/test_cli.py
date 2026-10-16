from pathlib import Path

import pandas as pd
import yaml

from manoj_bot.cli import main
from manoj_bot.config import BotConfig
from manoj_bot.engine import BotState, save_state
from manoj_bot.portfolio import Trade

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.yaml"


def write_config(tmp_path, **overrides):
    raw = yaml.safe_load(EXAMPLE.read_text())
    raw["state_file"] = str(tmp_path / "state.json")
    for key, value in overrides.items():
        section, _, name = key.partition("__")
        if name:
            raw[section][name] = value
        else:
            raw[key] = value
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    return str(path)


def test_backtest_on_synthetic_data(capsys):
    assert main(["backtest", "--bars", "300"]) == 0
    out = capsys.readouterr().out
    assert "synthetic" in out and "Total return" in out


def test_backtest_from_csv_with_parameters(tmp_path, capsys):
    days = pd.date_range("2023-01-01", periods=400, freq="D")
    rows = [f"{day:%Y-%m-%d},{p},{p},{p},{p}" for day, p in zip(days, range(100, 500), strict=True)]
    prices = tmp_path / "prices.csv"
    prices.write_text("\n".join(["date,open,high,low,close", *rows]) + "\n")
    trades = tmp_path / "trades.csv"
    args = ["backtest", "--csv", str(prices), "--strategy", "rsi_reversion", "-p", "period=5"]
    assert main([*args, "--trades-out", str(trades)]) == 0
    assert "RsiReversion(period=5" in capsys.readouterr().out
    assert trades.read_text().startswith("entry_time,exit_time")


def test_backtest_rejects_bad_parameters(capsys):
    assert main(["backtest", "-p", "fast"]) == 1
    assert "KEY=VALUE" in capsys.readouterr().err
    assert main(["backtest", "-p", "fast=100"]) == 1
    assert "smaller than slow" in capsys.readouterr().err


def test_strategies(capsys):
    assert main(["strategies"]) == 0
    out = capsys.readouterr().out
    assert "ma_crossover" in out and "rsi_reversion" in out


def test_live_mode_needs_explicit_confirmation(tmp_path, capsys):
    assert main(["run", "-c", write_config(tmp_path, mode="live")]) == 2
    assert "--confirm-live" in capsys.readouterr().err


def test_live_mode_needs_matching_exchanges(tmp_path, capsys):
    config = write_config(tmp_path, mode="live", broker__exchange="kraken")
    assert main(["run", "-c", config, "--confirm-live"]) == 1
    assert "must match" in capsys.readouterr().err


def test_run_needs_live_market_data(tmp_path, capsys):
    assert main(["run", "-c", write_config(tmp_path, data__source="synthetic")]) == 1
    assert "live market data" in capsys.readouterr().err


def test_status(tmp_path, capsys):
    config_path = write_config(tmp_path)
    assert main(["status", "-c", config_path]) == 0
    assert "No saved state" in capsys.readouterr().out

    state = BotState.new(BotConfig.load(config_path))
    state.trades.append(Trade("2024-01-01", "2024-01-02", 100, 110, 1, 10, 0.1, "signal"))
    save_state(tmp_path / "state.json", state)
    assert main(["status", "-c", config_path]) == 0
    out = capsys.readouterr().out
    assert "realised P&L 10.00" in out and "signal" in out
