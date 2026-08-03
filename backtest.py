"""Deterministic historical evaluation for the rule-based TABSS strategy."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import btc_agent


@dataclass
class BacktestResult:
    candles: int
    trades: int
    starting_cash: float
    ending_equity: float
    total_return_pct: float
    buy_hold_return_pct: float
    excess_return_pct: float
    max_drawdown_pct: float
    realized_pnl: float
    total_fees: float
    winning_round_trips: int
    losing_round_trips: int
    win_rate_pct: float


def run_backtest(
    klines: list[list[Any]],
    *,
    starting_cash: float = 1000.0,
    fee_rate_bps: float = 10.0,
    slippage_bps: float = 2.0,
    lookback: int = 250,
    symbol: str = "BTCUSDT",
    interval: str = "15m",
) -> BacktestResult:
    if starting_cash <= 0:
        raise ValueError("starting_cash must be positive")
    if lookback < 60:
        raise ValueError("lookback must be at least 60 candles")
    if not 0 <= fee_rate_bps < 10_000:
        raise ValueError("fee_rate_bps must be between 0 and 9999")
    if not 0 <= slippage_bps < 10_000:
        raise ValueError("slippage_bps must be between 0 and 9999")
    if len(klines) < 61:
        raise ValueError("At least 61 candles are required")

    config = btc_agent.AgentConfig(symbol=symbol, interval=interval, lookback=lookback)
    cash = starting_cash
    btc = 0.0
    entry_value = 0.0
    fees = 0.0
    trades = wins = losses = 0
    realized_pnl = 0.0
    peak_equity = starting_cash
    max_drawdown = 0.0
    fee_rate = fee_rate_bps / 10_000
    slippage_rate = slippage_bps / 10_000
    first_price = float(klines[60][1])

    # A signal is calculated after candle `index - 1` closes and is filled at
    # candle `index`'s open. This prevents same-candle look-ahead bias.
    for index in range(60, len(klines)):
        window = klines[max(0, index - lookback) : index]
        signal_price = float(window[-1][4])
        execution_open = float(klines[index][1])
        closing_price = float(klines[index][4])
        snapshot = btc_agent.analyze_market(window, signal_price, config)
        signal, _, _ = btc_agent.build_rule_based_signal(snapshot)

        if signal == "BUY" and btc == 0.0:
            execution_price = execution_open * (1 + slippage_rate)
            fee = cash * fee_rate
            entry_value = cash
            btc = (cash - fee) / execution_price
            cash = 0.0
            fees += fee
            trades += 1
        elif signal == "SELL" and btc > 0.0:
            execution_price = execution_open * (1 - slippage_rate)
            gross = btc * execution_price
            fee = gross * fee_rate
            cash = gross - fee
            pnl = cash - entry_value
            realized_pnl += pnl
            wins += pnl > 0
            losses += pnl <= 0
            btc = 0.0
            entry_value = 0.0
            fees += fee
            trades += 1

        equity = cash + (btc * closing_price)
        peak_equity = max(peak_equity, equity)
        max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity)

    last_price = float(klines[-1][4])
    ending_equity = cash + (btc * last_price)
    strategy_return = ((ending_equity / starting_cash) - 1) * 100
    buy_hold_return = ((last_price / first_price) - 1) * 100
    round_trips = wins + losses
    return BacktestResult(
        candles=len(klines) - 60,
        trades=trades,
        starting_cash=round(starting_cash, 2),
        ending_equity=round(ending_equity, 2),
        total_return_pct=round(strategy_return, 4),
        buy_hold_return_pct=round(buy_hold_return, 4),
        excess_return_pct=round(strategy_return - buy_hold_return, 4),
        max_drawdown_pct=round(max_drawdown * 100, 4),
        realized_pnl=round(realized_pnl, 2),
        total_fees=round(fees, 2),
        winning_round_trips=wins,
        losing_round_trips=losses,
        win_rate_pct=round((wins / round_trips * 100) if round_trips else 0.0, 2),
    )


def load_klines(path: Path) -> list[list[Any]]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("JSON input must be a Binance kline array")
        return payload

    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"open_time", "open", "high", "low", "close", "volume"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"CSV must contain: {', '.join(sorted(required))}")
    return [[row["open_time"], row["open"], row["high"], row["low"], row["close"], row["volume"]] for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest the TABSS rule-based signal strategy")
    parser.add_argument("input", type=Path, help="Binance kline JSON or OHLCV CSV")
    parser.add_argument("--starting-cash", type=float, default=1000.0)
    parser.add_argument("--fee-rate-bps", type=float, default=10.0)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--lookback", type=int, default=250)
    args = parser.parse_args()
    result = run_backtest(
        load_klines(args.input), starting_cash=args.starting_cash,
        fee_rate_bps=args.fee_rate_bps, slippage_bps=args.slippage_bps, lookback=args.lookback,
    )
    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
