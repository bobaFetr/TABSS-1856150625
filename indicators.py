"""Pure-Python technical indicators used by the signal engine and backtests."""

from __future__ import annotations


def ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        raise ValueError(f"Need at least {period} values for EMA")

    multiplier = 2 / (period + 1)
    seed = sum(values[:period]) / period
    result: list[float] = []
    for index, value in enumerate(values):
        if index <= period - 1:
            result.append(seed)
        else:
            result.append(((value - result[-1]) * multiplier) + result[-1])
    return result


def rsi(values: list[float], period: int = 14) -> list[float]:
    if len(values) <= period:
        raise ValueError(f"Need more than {period} values for RSI")

    gains: list[float] = []
    losses: list[float] = []
    output = [50.0] * len(values)
    for index in range(1, len(values)):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    output[period] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))

    for index in range(period + 1, len(values)):
        avg_gain = ((avg_gain * (period - 1)) + gains[index - 1]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[index - 1]) / period
        output[index] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))
    return output


def macd(
    values: list[float], fast_period: int = 12, slow_period: int = 26, signal_period: int = 9
) -> tuple[list[float], list[float], list[float]]:
    fast = ema(values, fast_period)
    slow = ema(values, slow_period)
    macd_line = [fast_value - slow_value for fast_value, slow_value in zip(fast, slow)]
    signal_line = ema(macd_line, signal_period)
    histogram = [value - signal for value, signal in zip(macd_line, signal_line)]
    return macd_line, signal_line, histogram


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    if len(closes) <= period:
        raise ValueError(f"Need more than {period} values for ATR")
    if len(highs) != len(closes) or len(lows) != len(closes):
        raise ValueError("High, low, and close series must have equal lengths")

    true_ranges: list[float] = []
    for index in range(len(closes)):
        if index == 0:
            true_ranges.append(highs[index] - lows[index])
        else:
            true_ranges.append(max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            ))

    output = [true_ranges[0]] * len(true_ranges)
    current = sum(true_ranges[1 : period + 1]) / period
    output[period] = current
    for index in range(period + 1, len(true_ranges)):
        current = ((current * (period - 1)) + true_ranges[index]) / period
        output[index] = current
    return output
