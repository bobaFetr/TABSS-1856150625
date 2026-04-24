from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UPDATE_OPTIONS = {
    "1": ("1 second", 1),
    "2": ("10 seconds", 10),
    "3": ("1 minute", 60),
}


def load_local_env(path: Path) -> None:
    if not path.exists():
        return

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

env_path = Path(__file__).with_name(".env")
load_local_env(env_path)
if "OPENAI_API_KEY" not in os.environ:
    load_local_env(Path(__file__).with_name(".env.example"))


def env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass
class AgentConfig:
    symbol: str = env_str("BINANCE_SYMBOL", "BTCUSDT")
    interval: str = env_str("BINANCE_INTERVAL", "15m")
    lookback: int = env_int("BINANCE_LOOKBACK", 250)
    poll_seconds: int = env_int("POLL_SECONDS", 60)
    base_url: str = env_str("BINANCE_BASE_URL", "https://api.binance.com")
    request_timeout: float = env_float("REQUEST_TIMEOUT", 10.0)
    buy_threshold: int = env_int("BUY_THRESHOLD", 4)
    sell_threshold: int = env_int("SELL_THRESHOLD", 4)
    state_file: str = env_str("STATE_FILE", "agent_state.json")
    openai_api_key: str = env_str("OPENAI_API_KEY", "")
    openai_model: str = env_str("OPENAI_MODEL", "gpt-4.1-nano")
    openai_base_url: str = env_str("OPENAI_BASE_URL", "https://api.openai.com/v1/responses")
    openai_timeout: float = env_float("OPENAI_TIMEOUT", 20.0)
    signal_refresh_seconds: int = env_int("SIGNAL_REFRESH_SECONDS", 300)


@dataclass
class AgentState:
    position: str = "FLAT"
    last_signal: str = "HOLD"
    last_updated: str = ""
    last_confidence: int = 50
    last_reasons: list[str] | None = None
    last_signal_refresh: str = ""
    last_snapshot_refresh: str = ""
    last_snapshot: dict[str, Any] | None = None


@dataclass
class SignalResult:
    signal: str
    execution_action: str
    confidence: int
    symbol: str
    interval: str
    price: float
    rsi: float
    ema_fast: float
    ema_mid: float
    ema_slow: float
    macd_histogram: float
    atr: float
    stop_loss: float | None
    take_profit: float | None
    bullish_score: int
    bearish_score: int
    reasons: list[str]
    timestamp_utc: str
    position_after_signal: str


@dataclass
class MarketSnapshot:
    symbol: str
    interval: str
    live_price: float
    candle_close_price: float
    rsi: float
    ema_fast: float
    ema_mid: float
    ema_slow: float
    macd_histogram: float
    atr: float
    bullish_score: int
    bearish_score: int
    reasons: list[str]


def snapshot_to_dict(snapshot: MarketSnapshot) -> dict[str, Any]:
    return asdict(snapshot)


def snapshot_from_dict(payload: dict[str, Any]) -> MarketSnapshot | None:
    required = {
        "symbol",
        "interval",
        "live_price",
        "candle_close_price",
        "rsi",
        "ema_fast",
        "ema_mid",
        "ema_slow",
        "macd_histogram",
        "atr",
        "bullish_score",
        "bearish_score",
        "reasons",
    }
    if not isinstance(payload, dict) or not required.issubset(payload):
        return None

    reasons = payload.get("reasons")
    if not isinstance(reasons, list):
        return None

    try:
        return MarketSnapshot(
            symbol=str(payload["symbol"]),
            interval=str(payload["interval"]),
            live_price=float(payload["live_price"]),
            candle_close_price=float(payload["candle_close_price"]),
            rsi=float(payload["rsi"]),
            ema_fast=float(payload["ema_fast"]),
            ema_mid=float(payload["ema_mid"]),
            ema_slow=float(payload["ema_slow"]),
            macd_histogram=float(payload["macd_histogram"]),
            atr=float(payload["atr"]),
            bullish_score=int(payload["bullish_score"]),
            bearish_score=int(payload["bearish_score"]),
            reasons=[str(reason) for reason in reasons],
        )
    except (TypeError, ValueError):
        return None


class BinanceClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        query = urllib.parse.urlencode(params)
        url = f"{self.base_url}{path}?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "btc-signal-agent/1.0",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"Binance request failed with HTTP {exc.code}: {body or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Binance: {exc.reason}") from exc

        return json.loads(payload)

    def get_klines(self, symbol: str, interval: str, limit: int) -> list[list[Any]]:
        data = self._get_json(
            "/api/v3/klines",
            {"symbol": symbol.upper(), "interval": interval, "limit": limit},
        )
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected Binance response: {data}")
        return data

    def get_ticker_price(self, symbol: str) -> float:
        data = self._get_json("/api/v3/ticker/price", {"symbol": symbol.upper()})
        if not isinstance(data, dict) or "price" not in data:
            raise RuntimeError(f"Unexpected Binance ticker response: {data}")
        return float(data["price"])


class OpenAIClient:
    def __init__(self, api_key: str, base_url: str, model: str, timeout: float) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    def get_signal(self, snapshot: MarketSnapshot, state: AgentState) -> tuple[str, int, list[str]]:
        schema = {
            "type": "object",
            "properties": {
                "signal": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
                "confidence": {"type": "integer"},
                "reasons": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["signal", "confidence", "reasons"],
            "additionalProperties": False,
        }

        instructions = (
            "You are a cautious BTCUSDT trading signal assistant. "
            "Given a compact market snapshot, decide BUY, SELL, or HOLD. "
            "Return HOLD when evidence is mixed or weak. "
            "Use only the provided data. "
            "Do not promise profit. "
            "Return concise JSON only."
        )

        rule_reasons = "\n".join(f"- {reason}" for reason in snapshot.reasons)
        prompt = (
            f"Symbol: {snapshot.symbol}\n"
            f"Interval: {snapshot.interval}\n"
            f"Live price: {snapshot.live_price:.2f}\n"
            f"Latest closed candle price: {snapshot.candle_close_price:.2f}\n"
            f"RSI: {snapshot.rsi:.2f}\n"
            f"EMA 9: {snapshot.ema_fast:.2f}\n"
            f"EMA 21: {snapshot.ema_mid:.2f}\n"
            f"EMA 55: {snapshot.ema_slow:.2f}\n"
            f"MACD histogram: {snapshot.macd_histogram:.4f}\n"
            f"ATR: {snapshot.atr:.2f}\n"
            f"Bullish score: {snapshot.bullish_score}\n"
            f"Bearish score: {snapshot.bearish_score}\n"
            f"Current position state: {state.position}\n"
            "Rule-based context:\n"
            f"{rule_reasons}"
        )

        payload = {
            "model": self.model,
            "instructions": instructions,
            "input": prompt,
            "max_output_tokens": 220,
            "temperature": 0.2,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "btc_signal",
                    "strict": True,
                    "schema": schema,
                }
            },
        }

        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"OpenAI request failed with HTTP {exc.code}: {error_body or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach OpenAI: {exc.reason}") from exc

        payload = json.loads(body)
        response_text = extract_response_text(payload)

        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"OpenAI returned invalid JSON: {response_text}") from exc

        signal = str(parsed.get("signal", "HOLD")).upper()
        if signal not in {"BUY", "SELL", "HOLD"}:
            signal = "HOLD"

        confidence = clamp(int(parsed.get("confidence", 50)), 0, 100)
        reasons = parsed.get("reasons", [])
        if not isinstance(reasons, list) or not reasons:
            reasons = ["OpenAI returned no usable reasons, so the agent stayed cautious."]

        return signal, confidence, [str(reason) for reason in reasons[:3]]


def extract_response_text(payload: dict[str, Any]) -> str:
    output = payload.get("output", [])
    if not isinstance(output, list):
        raise RuntimeError(f"Unexpected OpenAI response payload: {payload}")

    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content", [])
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "output_text" and "text" in part:
                return str(part["text"])

    raise RuntimeError(f"Could not extract text from OpenAI response: {payload}")


def load_state(path: Path) -> AgentState:
    if not path.exists():
        return AgentState()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return AgentState()

    return AgentState(
        position=str(raw.get("position", "FLAT")).upper(),
        last_signal=str(raw.get("last_signal", "HOLD")).upper(),
        last_updated=str(raw.get("last_updated", "")),
        last_confidence=int(raw.get("last_confidence", 50)),
        last_reasons=raw.get("last_reasons") if isinstance(raw.get("last_reasons"), list) else None,
        last_signal_refresh=str(raw.get("last_signal_refresh", "")),
        last_snapshot_refresh=str(raw.get("last_snapshot_refresh", "")),
        last_snapshot=raw.get("last_snapshot") if isinstance(raw.get("last_snapshot"), dict) else None,
    )


def save_state(path: Path, state: AgentState) -> None:
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


def ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        raise ValueError(f"Need at least {period} values for EMA")

    multiplier = 2 / (period + 1)
    result: list[float] = []
    seed = sum(values[:period]) / period

    for index, value in enumerate(values):
        if index < period - 1:
            result.append(seed)
        elif index == period - 1:
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

    if avg_loss == 0:
        output[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        output[period] = 100 - (100 / (1 + rs))

    for index in range(period + 1, len(values)):
        gain = gains[index - 1]
        loss = losses[index - 1]
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period

        if avg_loss == 0:
            output[index] = 100.0
        else:
            rs = avg_gain / avg_loss
            output[index] = 100 - (100 / (1 + rs))

    return output


def macd(
    values: list[float], fast_period: int = 12, slow_period: int = 26, signal_period: int = 9
) -> tuple[list[float], list[float], list[float]]:
    fast = ema(values, fast_period)
    slow = ema(values, slow_period)
    macd_line = [fast_value - slow_value for fast_value, slow_value in zip(fast, slow)]
    signal_line = ema(macd_line, signal_period)
    histogram = [macd_value - signal_value for macd_value, signal_value in zip(macd_line, signal_line)]
    return macd_line, signal_line, histogram


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    if len(closes) <= period:
        raise ValueError(f"Need more than {period} values for ATR")

    true_ranges: list[float] = []
    for index in range(len(closes)):
        if index == 0:
            true_ranges.append(highs[index] - lows[index])
            continue

        true_ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )

    output = [true_ranges[0]] * len(true_ranges)
    seed = sum(true_ranges[1 : period + 1]) / period
    output[period] = seed

    current = seed
    for index in range(period + 1, len(true_ranges)):
        current = ((current * (period - 1)) + true_ranges[index]) / period
        output[index] = current

    return output


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def parse_iso_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def analyze_market(klines: list[list[Any]], live_price: float, config: AgentConfig) -> MarketSnapshot:
    if len(klines) < 60:
        raise RuntimeError("Not enough candle data returned from Binance")

    closes = [float(entry[4]) for entry in klines]
    highs = [float(entry[2]) for entry in klines]
    lows = [float(entry[3]) for entry in klines]
    volumes = [float(entry[5]) for entry in klines]

    ema_fast_values = ema(closes, 9)
    ema_mid_values = ema(closes, 21)
    ema_slow_values = ema(closes, 55)
    rsi_values = rsi(closes, 14)
    _, _, macd_histogram_values = macd(closes)
    atr_values = atr(highs, lows, closes, 14)

    latest_close_price = closes[-1]
    previous_close_price = closes[-2]
    latest_rsi = rsi_values[-1]
    previous_rsi = rsi_values[-2]
    latest_ema_fast = ema_fast_values[-1]
    latest_ema_mid = ema_mid_values[-1]
    latest_ema_slow = ema_slow_values[-1]
    latest_macd_histogram = macd_histogram_values[-1]
    previous_macd_histogram = macd_histogram_values[-2]
    latest_atr = atr_values[-1]
    latest_volume = volumes[-1]
    average_volume = sum(volumes[-20:]) / min(20, len(volumes))

    bullish_score = 0
    bearish_score = 0
    reasons: list[str] = []

    if latest_ema_fast > latest_ema_mid > latest_ema_slow:
        bullish_score += 2
        reasons.append("Short-term trend is above medium and long trend.")
    elif latest_ema_fast < latest_ema_mid < latest_ema_slow:
        bearish_score += 2
        reasons.append("Short-term trend is below medium and long trend.")

    if (
        latest_close_price > latest_ema_fast
        and latest_macd_histogram > 0
        and latest_macd_histogram > previous_macd_histogram
    ):
        bullish_score += 2
        reasons.append("Price is above the fast EMA and MACD momentum is improving.")
    elif (
        latest_close_price < latest_ema_fast
        and latest_macd_histogram < 0
        and latest_macd_histogram < previous_macd_histogram
    ):
        bearish_score += 2
        reasons.append("Price is below the fast EMA and MACD momentum is weakening.")

    if latest_rsi < 30 and latest_rsi > previous_rsi:
        bullish_score += 2
        reasons.append("RSI is recovering from oversold territory.")
    elif 40 <= latest_rsi <= 68 and latest_rsi > previous_rsi:
        bullish_score += 1
        reasons.append("RSI shows constructive upward momentum without being overbought.")
    elif latest_rsi > 70 and latest_rsi < previous_rsi:
        bearish_score += 2
        reasons.append("RSI is rolling over from overbought territory.")
    elif 32 <= latest_rsi <= 55 and latest_rsi < previous_rsi:
        bearish_score += 1
        reasons.append("RSI is fading inside a weak momentum zone.")

    if latest_volume > average_volume * 1.25:
        if latest_close_price >= previous_close_price:
            bullish_score += 1
            reasons.append("Volume expanded behind the latest upward candle.")
        else:
            bearish_score += 1
            reasons.append("Volume expanded behind the latest downward candle.")

    score_gap = bullish_score - bearish_score
    if score_gap >= config.buy_threshold:
        reasons.append("Rule-based score is tilted bullish.")
    elif score_gap <= -config.sell_threshold:
        reasons.append("Rule-based score is tilted bearish.")
    else:
        reasons.append("Rule-based score is mixed.")

    return MarketSnapshot(
        symbol=config.symbol,
        interval=config.interval,
        live_price=live_price,
        candle_close_price=latest_close_price,
        rsi=latest_rsi,
        ema_fast=latest_ema_fast,
        ema_mid=latest_ema_mid,
        ema_slow=latest_ema_slow,
        macd_histogram=latest_macd_histogram,
        atr=latest_atr,
        bullish_score=bullish_score,
        bearish_score=bearish_score,
        reasons=reasons,
    )


def build_signal_result(
    snapshot: MarketSnapshot, state: AgentState, signal: str, confidence: int, reasons: list[str]
) -> SignalResult:
    execution_action = "WAIT"
    next_position = state.position

    if signal == "BUY" and state.position != "LONG":
        execution_action = "BUY"
        next_position = "LONG"
    elif signal == "SELL" and state.position == "LONG":
        execution_action = "SELL"
        next_position = "FLAT"
    elif signal == "SELL" and state.position != "LONG":
        execution_action = "STAY_OUT"

    stop_loss = None
    take_profit = None
    if execution_action == "BUY":
        stop_loss = snapshot.live_price - (1.5 * snapshot.atr)
        take_profit = snapshot.live_price + (3.0 * snapshot.atr)
    elif execution_action in {"SELL", "STAY_OUT"}:
        stop_loss = snapshot.live_price + (1.5 * snapshot.atr)
        take_profit = snapshot.live_price - (3.0 * snapshot.atr)

    return SignalResult(
        signal=signal,
        execution_action=execution_action,
        confidence=confidence,
        symbol=snapshot.symbol,
        interval=snapshot.interval,
        price=snapshot.live_price,
        rsi=snapshot.rsi,
        ema_fast=snapshot.ema_fast,
        ema_mid=snapshot.ema_mid,
        ema_slow=snapshot.ema_slow,
        macd_histogram=snapshot.macd_histogram,
        atr=snapshot.atr,
        stop_loss=round(stop_loss, 2) if stop_loss is not None else None,
        take_profit=round(take_profit, 2) if take_profit is not None else None,
        bullish_score=snapshot.bullish_score,
        bearish_score=snapshot.bearish_score,
        reasons=reasons,
        timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        position_after_signal=next_position,
    )


def build_rule_based_signal(snapshot: MarketSnapshot) -> tuple[str, int, list[str]]:
    score_gap = snapshot.bullish_score - snapshot.bearish_score
    if score_gap >= 4:
        signal = "BUY"
    elif score_gap <= -4:
        signal = "SELL"
    else:
        signal = "HOLD"

    confidence = clamp(int((max(snapshot.bullish_score, snapshot.bearish_score) / 7) * 100), 0, 100)
    reasons = list(snapshot.reasons[-3:]) if snapshot.reasons else ["Signals are mixed, so the agent stayed neutral."]
    return signal, confidence, reasons


def should_refresh_from_timestamp(last_refresh_value: str, refresh_seconds: int) -> bool:
    last_refresh = parse_iso_timestamp(last_refresh_value)
    if last_refresh is None:
        return True

    elapsed = (datetime.now(timezone.utc) - last_refresh.astimezone(timezone.utc)).total_seconds()
    return elapsed >= refresh_seconds


def get_market_snapshot(
    binance_client: BinanceClient, config: AgentConfig, state: AgentState
) -> tuple[MarketSnapshot, bool]:
    live_price = binance_client.get_ticker_price(config.symbol)
    cached_snapshot = snapshot_from_dict(state.last_snapshot or {})

    if cached_snapshot and not should_refresh_from_timestamp(
        state.last_snapshot_refresh, config.signal_refresh_seconds
    ):
        cached_snapshot.live_price = live_price
        return cached_snapshot, False

    klines = binance_client.get_klines(config.symbol, config.interval, config.lookback)
    fresh_snapshot = analyze_market(klines, live_price, config)
    return fresh_snapshot, True


def print_signal(result: SignalResult) -> None:
    print(json.dumps(asdict(result), indent=2))


def prompt_poll_seconds() -> int:
    print("")
    print("Choose the BTC price update speed:")
    print("1. 1 second")
    print("2. 10 seconds")
    print("3. 1 minute")
    print("")

    while True:
        choice = input("Select 1, 2, or 3: ").strip()
        if choice in UPDATE_OPTIONS:
            label, seconds = UPDATE_OPTIONS[choice]
            print(f"Selected {label}.")
            print("")
            return seconds
        print("Invalid choice. Please enter 1, 2, or 3.")


def format_change(current_price: float, previous_price: float | None) -> str:
    if previous_price is None:
        return "NEW"

    delta = current_price - previous_price
    if delta > 0:
        return f"UP +${delta:.2f}"
    if delta < 0:
        return f"DOWN -${abs(delta):.2f}"
    return "UNCHANGED"


def print_tracker_update(result: SignalResult, previous_price: float | None) -> None:
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    price_move = format_change(result.price, previous_price)
    print(
        f"[{timestamp}] "
        f"BTC: ${result.price:.2f} | "
        f"{price_move} | "
        f"Signal: {result.signal} | "
        f"Action: {result.execution_action} | "
        f"Confidence: {result.confidence}%"
    )


def config_from_args(args: argparse.Namespace) -> AgentConfig:
    return AgentConfig(
        symbol=args.symbol.upper(),
        interval=args.interval,
        lookback=args.lookback,
        poll_seconds=args.poll_seconds,
        base_url=args.base_url,
        request_timeout=args.request_timeout,
        buy_threshold=args.buy_threshold,
        sell_threshold=args.sell_threshold,
        state_file=args.state_file,
        openai_api_key=env_str("OPENAI_API_KEY", ""),
        openai_model=env_str("OPENAI_MODEL", "gpt-4.1-nano"),
        openai_base_url=env_str("OPENAI_BASE_URL", "https://api.openai.com/v1/responses"),
        openai_timeout=env_float("OPENAI_TIMEOUT", 20.0),
        signal_refresh_seconds=env_int("SIGNAL_REFRESH_SECONDS", 300),
    )


def build_parser(defaults: AgentConfig, include_once: bool = True) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Track BTC on Binance and emit buy/sell/hold signals."
    )
    parser.add_argument("--symbol", default=defaults.symbol, help="Trading pair, for example BTCUSDT.")
    parser.add_argument("--interval", default=defaults.interval, help="Binance kline interval, for example 1m, 15m, 1h.")
    parser.add_argument("--lookback", type=int, default=defaults.lookback, help="Number of candles to fetch.")
    parser.add_argument("--poll-seconds", type=int, help="Delay between checks in live mode.")
    parser.add_argument("--base-url", default=defaults.base_url, help="Binance REST base URL.")
    parser.add_argument("--request-timeout", type=float, default=defaults.request_timeout, help="HTTP timeout in seconds.")
    parser.add_argument("--buy-threshold", type=int, default=defaults.buy_threshold, help="Bullish score gap used in the market snapshot.")
    parser.add_argument("--sell-threshold", type=int, default=defaults.sell_threshold, help="Bearish score gap used in the market snapshot.")
    parser.add_argument("--state-file", default=defaults.state_file, help="Where to store the local position state.")
    if include_once:
        parser.add_argument("--once", action="store_true", help="Run once and exit.")
    return parser


def run_cycle(config: AgentConfig) -> SignalResult:
    binance_client = BinanceClient(base_url=config.base_url, timeout=config.request_timeout)
    state_path = Path(config.state_file)
    state = load_state(state_path)
    snapshot, snapshot_refreshed = get_market_snapshot(binance_client, config, state)
    signal: str
    confidence: int
    reasons: list[str]
    refreshed_at = state.last_signal_refresh
    snapshot_refreshed_at = state.last_snapshot_refresh

    if config.openai_api_key and snapshot_refreshed:
        snapshot_refreshed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        openai_client = OpenAIClient(
            api_key=config.openai_api_key,
            base_url=config.openai_base_url,
            model=config.openai_model,
            timeout=config.openai_timeout,
        )
        try:
            signal, confidence, reasons = openai_client.get_signal(snapshot, state)
            refreshed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        except RuntimeError as exc:
            if state.last_reasons:
                signal = state.last_signal
                confidence = state.last_confidence
                reasons = [f"Using cached AI signal because OpenAI is unavailable: {exc}"]
            else:
                signal, confidence, reasons = build_rule_based_signal(snapshot)
                reasons = [f"Using rule-based fallback because OpenAI is unavailable: {exc}"] + reasons[:2]
    elif config.openai_api_key and state.last_reasons:
        signal = state.last_signal
        confidence = state.last_confidence
        reasons = state.last_reasons
    elif config.openai_api_key:
        signal, confidence, reasons = build_rule_based_signal(snapshot)
    else:
        signal, confidence, reasons = build_rule_based_signal(snapshot)
        reasons = ["Using rule-based fallback because OPENAI_API_KEY is missing."] + reasons[:2]

    if snapshot_refreshed and not snapshot_refreshed_at:
        snapshot_refreshed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    result = build_signal_result(snapshot, state, signal, confidence, reasons)

    save_state(
        state_path,
        AgentState(
            position=result.position_after_signal,
            last_signal=result.signal,
            last_updated=result.timestamp_utc,
            last_confidence=result.confidence,
            last_reasons=result.reasons,
            last_signal_refresh=refreshed_at,
            last_snapshot_refresh=snapshot_refreshed_at,
            last_snapshot=snapshot_to_dict(snapshot),
        ),
    )
    return result


def print_startup_status(config: AgentConfig) -> None:
    try:
        quick_client = BinanceClient(base_url=config.base_url, timeout=min(config.request_timeout, 5.0))
        quick_price = quick_client.get_ticker_price(config.symbol)
        print(f"Live BTC price now: ${quick_price:.2f}")
    except Exception:  # noqa: BLE001
        print("Fetching live BTC price...")

    print("Loading the first full market snapshot. This can take a few seconds.")
    print("")


def main() -> int:
    defaults = AgentConfig()
    parser = build_parser(defaults)
    args = parser.parse_args()
    if not getattr(args, "once", False) and args.poll_seconds is None:
        args.poll_seconds = prompt_poll_seconds()
    elif args.poll_seconds is None:
        args.poll_seconds = defaults.poll_seconds

    config = config_from_args(args)
    previous_price: float | None = None

    try:
        print(f"Using OpenAI model: {config.openai_model}")
        print(f"Signal refresh interval: {config.signal_refresh_seconds} second(s)")
        print(f"Tracking {config.symbol} from Binance every {config.poll_seconds} second(s).")
        print("Press Ctrl+C to stop.")
        print("")
        print_startup_status(config)

        while True:
            cycle_started = time.monotonic()
            result = run_cycle(config)
            if args.once:
                print_signal(result)
                return 0

            print_tracker_update(result, previous_price)
            previous_price = result.price
            elapsed = time.monotonic() - cycle_started
            sleep_seconds = max(0.0, config.poll_seconds - elapsed)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Agent error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
