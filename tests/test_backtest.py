from __future__ import annotations

import unittest
from unittest.mock import patch

import backtest


def synthetic_klines(count: int = 100) -> list[list[object]]:
    rows: list[list[object]] = []
    for index in range(count):
        close = 100.0 + (index * 0.4) + ((index % 8) - 4)
        rows.append([index, close - 0.5, close + 1.0, close - 1.0, close, 1000 + index])
    return rows


class BacktestTests(unittest.TestCase):
    def test_backtest_is_deterministic_and_reports_benchmark(self) -> None:
        first = backtest.run_backtest(synthetic_klines())
        second = backtest.run_backtest(synthetic_klines())
        self.assertEqual(first, second)
        self.assertEqual(first.candles, 40)
        self.assertGreater(first.buy_hold_return_pct, 0)
        self.assertGreaterEqual(first.max_drawdown_pct, 0)
        self.assertLessEqual(first.win_rate_pct, 100)

    def test_backtest_requires_enough_data(self) -> None:
        with self.assertRaisesRegex(ValueError, "61 candles"):
            backtest.run_backtest(synthetic_klines(60))

    def test_backtest_rejects_non_positive_cash(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            backtest.run_backtest(synthetic_klines(), starting_cash=0)

    def test_backtest_rejects_invalid_costs_and_lookback(self) -> None:
        with self.assertRaisesRegex(ValueError, "lookback"):
            backtest.run_backtest(synthetic_klines(), lookback=59)
        with self.assertRaisesRegex(ValueError, "fee_rate_bps"):
            backtest.run_backtest(synthetic_klines(), fee_rate_bps=-1)
        with self.assertRaisesRegex(ValueError, "slippage_bps"):
            backtest.run_backtest(synthetic_klines(), slippage_bps=10_000)

    def test_execution_uses_next_candle_open(self) -> None:
        rows = synthetic_klines()
        rows[60][1] = 10_000.0
        with patch("backtest.btc_agent.build_rule_based_signal", return_value=("BUY", 80, [])):
            result = backtest.run_backtest(rows)
            baseline = backtest.run_backtest(synthetic_klines())
        self.assertEqual(result.trades, 1)
        self.assertNotEqual(result.ending_equity, baseline.ending_equity)


if __name__ == "__main__":
    unittest.main()
