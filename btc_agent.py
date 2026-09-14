from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import ap2_sim
from validation import finite_number
from exchange import BinanceClient
from indicators import atr, ema, macd, rsi


UPDATE_OPTIONS = {
    "1": ("1 second", 1),
    "2": ("10 seconds", 10),
    "3": ("1 minute", 60),
}

_STATE_LOCK = threading.RLock()


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

# Only the untracked runtime file may provide credentials. The committed
# .env.example is documentation and must never be treated as a secret source.
env_path = Path(__file__).with_name(".env")
load_local_env(env_path)


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
        return finite_number(value, name)
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
    binance_retry_count: int = env_int("BINANCE_RETRY_COUNT", 3)
    binance_retry_delay_seconds: float = env_float("BINANCE_RETRY_DELAY_SECONDS", 2.0)


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
class SimulationConfig:
    enabled: bool = False
    buy_cooldown_seconds: int = 0
    drop_to_buy_usd: float = 0.0
    rise_to_sell_usd: float = 0.0
    starting_cash: float = 1000.0
    fee_rate_bps: float = 10.0
    slippage_bps: float = 2.0
    require_signal_confirmation: bool = False


@dataclass
class SimulationState:
    cash_balance: float
    btc_balance: float
    next_buy_monotonic: float
    last_buy_monotonic: float | None = None
    entry_cash_value: float = 0.0
    entry_price: float | None = None
    realized_pnl: float = 0.0
    trade_count: int = 0
    total_fees_usd: float = 0.0
    total_slippage_cost_usd: float = 0.0
    last_seen_price: float | None = None
    active_intent_mandate: dict[str, Any] | None = None


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
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(json.dumps(asdict(state), indent=2) + "\n", encoding="utf-8")
        os.replace(temporary_path, path)
    finally:
        with contextlib.suppress(OSError):
            temporary_path.unlink()


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


def prompt_positive_int(message: str) -> int:
    while True:
        value = input(message).strip()
        try:
            parsed = int(value)
        except ValueError:
            print("Please enter a whole number.")
            continue

        if parsed > 0:
            return parsed
        print("Please enter a number greater than 0.")


def prompt_positive_float(message: str) -> float:
    while True:
        value = input(message).strip()
        try:
            parsed = float(value)
        except ValueError:
            print("Please enter a valid number.")
            continue

        if parsed > 0:
            return parsed
        print("Please enter a number greater than 0.")


def prompt_starting_cash(max_amount: float = 1000.0) -> float:
    while True:
        value = input(f"How much money do you want to start with? Max ${max_amount:.2f}: ").strip()
        try:
            parsed = float(value)
        except ValueError:
            print("Please enter a valid number.")
            continue

        if parsed <= 0:
            print("Please enter a number greater than 0.")
            continue
        if parsed > max_amount:
            print(f"Please enter ${max_amount:.2f} or less.")
            continue
        return round(parsed, 2)


def prompt_startup_mode() -> tuple[int, SimulationConfig]:
    print("")
    print("Choose a start option:")
    print("1. Track price every 1 second")
    print("2. Track price every 10 seconds")
    print("3. Track price every 1 minute")
    print("5. Simulate auto buy and sell")
    print("")

    while True:
        choice = input("Select 1, 2, 3, or 5: ").strip()
        if choice in UPDATE_OPTIONS:
            label, seconds = UPDATE_OPTIONS[choice]
            print(f"Selected {label}.")
            print("")
            return seconds, SimulationConfig()

        if choice == "5":
            print("")
            print("Auto simulation mode selected.")
            print("The app will buy when BTC is dropping and sell when BTC is rising.")
            print("You can choose the starting simulation balance, up to $1000.00.")
            print("")
            poll_seconds = prompt_poll_seconds()
            starting_cash = prompt_starting_cash(1000.0)
            buy_cooldown_seconds = prompt_positive_int("How often can the agent buy again, in seconds? ")
            drop_to_buy_usd = prompt_positive_float(
                "Buy when BTC drops by how many USD from the previous observed price? "
            )
            rise_to_sell_usd = prompt_positive_float(
                "Sell when BTC rises by how many USD above the buy price? "
            )
            print("")
            print(
                "Auto simulation configured: "
                f"starting cash ${starting_cash:.2f}, "
                f"buy cooldown {buy_cooldown_seconds} second(s), "
                f"buy after a ${drop_to_buy_usd:.2f} drop, "
                f"sell after a ${rise_to_sell_usd:.2f} rise from entry."
            )
            print("")
            return poll_seconds, SimulationConfig(
                enabled=True,
                buy_cooldown_seconds=buy_cooldown_seconds,
                drop_to_buy_usd=drop_to_buy_usd,
                rise_to_sell_usd=rise_to_sell_usd,
                starting_cash=starting_cash,
            )

        print("Invalid choice. Please enter 1, 2, 3, or 5.")


def format_change(current_price: float, previous_price: float | None) -> str:
    if previous_price is None:
        return "NEW"

    delta = current_price - previous_price
    if delta > 0:
        return f"UP +${delta:.2f}"
    if delta < 0:
        return f"DOWN -${abs(delta):.2f}"
    return "UNCHANGED"


def create_simulation_state(config: SimulationConfig) -> SimulationState:
    return SimulationState(
        cash_balance=config.starting_cash,
        btc_balance=0.0,
        next_buy_monotonic=time.monotonic(),
    )


def initialize_ap2_simulation(symbol: str, config: SimulationConfig) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        intent_record = ap2_sim.create_intent_mandate(
            symbol=symbol,
            starting_cash_usd=config.starting_cash,
            buy_cooldown_seconds=config.buy_cooldown_seconds,
            buy_threshold_usd=config.drop_to_buy_usd,
            sell_threshold_usd=config.rise_to_sell_usd,
            fee_rate_bps=config.fee_rate_bps,
            slippage_bps=config.slippage_bps,
            require_signal_confirmation=config.require_signal_confirmation,
        )
    except Exception as exc:  # noqa: BLE001
        return None, [f"AP2 SIM | BLOCKED | Could not create Intent Mandate: {exc}"]

    intent_id = intent_record["payload"]["mandateId"]
    return intent_record, [
        f"AP2 SIM | Intent Mandate created: {intent_id}",
        "AP2 SIM | Mode: SIMULATION only | Real money: disabled",
    ]


def create_buy_cart_mandate(
    result: SignalResult,
    config: SimulationConfig,
    state: SimulationState,
    previous_seen_price: float,
) -> tuple[dict[str, Any] | None, str]:
    intent_record = state.active_intent_mandate
    if intent_record is None:
        return None, "No active Intent Mandate is available for simulated BUY."

    execution_price = result.price * (1 + (config.slippage_bps / 10000))
    fee = state.cash_balance * (config.fee_rate_bps / 10000)
    quantity = (state.cash_balance - fee) / execution_price if execution_price > 0 else 0.0
    price_change = result.price - previous_seen_price
    reason = (
        f"BTC dropped by ${abs(price_change):.2f} from the previous observed price, "
        f"exceeding the ${config.drop_to_buy_usd:.2f} buy threshold."
    )
    cart_record = ap2_sim.create_cart_mandate(
        intent_record=intent_record,
        action="BUY",
        symbol=result.symbol,
        price=execution_price,
        quantity=quantity,
        notional_usd=state.cash_balance,
        ai_signal=result.signal,
        ai_confidence=result.confidence,
        rule_trigger={
            "previousPrice": round(previous_seen_price, 2),
            "currentPrice": round(result.price, 2),
            "priceChangeUsd": round(price_change, 2),
            "buyThresholdUsd": round(config.drop_to_buy_usd, 2),
            "marketPrice": round(result.price, 2),
            "slippageBps": config.slippage_bps,
            "feeRateBps": config.fee_rate_bps,
        },
        reason=reason,
    )
    return cart_record, reason


def create_sell_cart_mandate(
    result: SignalResult,
    config: SimulationConfig,
    state: SimulationState,
) -> tuple[dict[str, Any] | None, str]:
    intent_record = state.active_intent_mandate
    if intent_record is None:
        return None, "No active Intent Mandate is available for simulated SELL."

    if state.entry_price is None:
        return None, "No simulated entry price is available for the SELL."

    rise_from_entry = result.price - state.entry_price
    execution_price = result.price * (1 - (config.slippage_bps / 10000))
    gross_received = state.btc_balance * execution_price
    fee = gross_received * (config.fee_rate_bps / 10000)
    net_received = gross_received - fee
    reason = (
        f"BTC rose by ${rise_from_entry:.2f} from entry, "
        f"exceeding the ${config.rise_to_sell_usd:.2f} sell threshold."
    )
    cart_record = ap2_sim.create_cart_mandate(
        intent_record=intent_record,
        action="SELL",
        symbol=result.symbol,
        price=execution_price,
        quantity=state.btc_balance,
        notional_usd=net_received,
        ai_signal=result.signal,
        ai_confidence=result.confidence,
        rule_trigger={
            "entryPrice": round(state.entry_price, 2),
            "currentPrice": round(result.price, 2),
            "riseFromEntryUsd": round(rise_from_entry, 2),
            "sellThresholdUsd": round(config.rise_to_sell_usd, 2),
            "marketPrice": round(result.price, 2),
            "slippageBps": config.slippage_bps,
            "feeRateBps": config.fee_rate_bps,
        },
        reason=reason,
    )
    return cart_record, reason


def block_ap2_trade(
    *,
    action: str,
    reason: str,
    state: SimulationState,
    cart_record: dict[str, Any] | None = None,
) -> list[str]:
    intent_id = None
    if state.active_intent_mandate and isinstance(state.active_intent_mandate.get("payload"), dict):
        intent_id = state.active_intent_mandate["payload"].get("mandateId")

    ap2_sim.log_validation_failed(
        reason=reason,
        intent_mandate_id=intent_id,
        cart_record=cart_record,
        action=action,
    )
    ap2_sim.log_trade_blocked(
        reason=reason,
        intent_mandate_id=intent_id,
        cart_record=cart_record,
        action=action,
    )
    return [f"AP2 SIM | BLOCKED | {reason}"]


def execute_ap2_buy(
    result: SignalResult,
    config: SimulationConfig,
    state: SimulationState,
    previous_seen_price: float,
) -> list[str]:
    cart_record, cart_reason = create_buy_cart_mandate(result, config, state, previous_seen_price)
    if cart_record is None:
        return block_ap2_trade(action="BUY", reason=cart_reason, state=state)

    messages = [
        f"AP2 SIM | Cart Mandate created: {cart_record['payload']['mandateId']} | Proposed BUY"
    ]
    valid, validation_reason, active_intent = ap2_sim.validate_cart_mandate(
        cart_record=cart_record,
        expected_symbol=result.symbol,
        available_cash=state.cash_balance,
        available_btc=state.btc_balance,
    )
    if not valid or active_intent is None:
        messages.extend(block_ap2_trade(action="BUY", reason=validation_reason, state=state, cart_record=cart_record))
        return messages

    state.active_intent_mandate = active_intent
    cash_before = state.cash_balance
    btc_before = state.btc_balance
    spent = state.cash_balance
    execution_price = float(cart_record["payload"]["price"])
    fee = spent * (config.fee_rate_bps / 10000)
    trade_notional = spent - fee
    btc_after = trade_notional / execution_price
    slippage_cost = btc_after * max(0.0, execution_price - result.price)

    payment_reason = (
        "Simulated BUY executed because the Cart Mandate matched the active Intent Mandate "
        "and all simulation risk checks passed."
    )
    payment_record = ap2_sim.create_payment_mandate(
        intent_record=active_intent,
        cart_record=cart_record,
        action="BUY",
        symbol=result.symbol,
        execution_price=execution_price,
        quantity=btc_after,
        notional_usd=spent,
        cash_before=cash_before,
        cash_after=0.0,
        btc_before=btc_before,
        btc_after=btc_after,
        reason=payment_reason,
        market_price=result.price,
        fee_usd=fee,
        slippage_bps=config.slippage_bps,
    )

    state.btc_balance = btc_after
    state.cash_balance = 0.0
    state.entry_cash_value = spent
    state.entry_price = execution_price
    state.total_fees_usd += fee
    state.total_slippage_cost_usd += slippage_cost
    state.last_buy_monotonic = time.monotonic()
    state.trade_count += 1

    messages.append(
        f"AUTO BUY | Spent ${spent:.2f} | Fee ${fee:.2f} | Bought {state.btc_balance:.8f} BTC "
        f"at effective ${execution_price:.2f} (market ${result.price:.2f}) "
        f"after a ${previous_seen_price - result.price:.2f} drop | "
        f"Cash: ${cash_before:.2f} -> ${state.cash_balance:.2f}"
    )
    messages.append(
        f"AP2 SIM | Payment Mandate created: {payment_record['payload']['mandateId']} | SIMULATED_EXECUTED"
    )
    return messages


def execute_ap2_sell(
    result: SignalResult,
    config: SimulationConfig,
    state: SimulationState,
) -> list[str]:
    cart_record, cart_reason = create_sell_cart_mandate(result, config, state)
    if cart_record is None:
        return block_ap2_trade(action="SELL", reason=cart_reason, state=state)

    messages = [
        f"AP2 SIM | Cart Mandate created: {cart_record['payload']['mandateId']} | Proposed SELL"
    ]
    valid, validation_reason, active_intent = ap2_sim.validate_cart_mandate(
        cart_record=cart_record,
        expected_symbol=result.symbol,
        available_cash=state.cash_balance,
        available_btc=state.btc_balance,
    )
    if not valid or active_intent is None:
        messages.extend(block_ap2_trade(action="SELL", reason=validation_reason, state=state, cart_record=cart_record))
        return messages

    state.active_intent_mandate = active_intent
    entry_price = state.entry_price or result.price
    cash_before = state.cash_balance
    btc_before = state.btc_balance
    execution_price = float(cart_record["payload"]["price"])
    gross_received = state.btc_balance * execution_price
    fee = gross_received * (config.fee_rate_bps / 10000)
    received = gross_received - fee
    slippage_cost = state.btc_balance * max(0.0, result.price - execution_price)
    equity_before = state.btc_balance * result.price
    pnl = received - state.entry_cash_value
    pnl_pct = (pnl / state.entry_cash_value * 100) if state.entry_cash_value else 0.0

    payment_reason = (
        "Simulated SELL executed because the Cart Mandate matched the active Intent Mandate "
        "and all simulation risk checks passed."
    )
    payment_record = ap2_sim.create_payment_mandate(
        intent_record=active_intent,
        cart_record=cart_record,
        action="SELL",
        symbol=result.symbol,
        execution_price=execution_price,
        quantity=btc_before,
        notional_usd=received,
        cash_before=cash_before,
        cash_after=received,
        btc_before=btc_before,
        btc_after=0.0,
        reason=payment_reason,
        market_price=result.price,
        fee_usd=fee,
        slippage_bps=config.slippage_bps,
    )

    state.realized_pnl += pnl
    state.total_fees_usd += fee
    state.total_slippage_cost_usd += slippage_cost
    state.cash_balance = received
    state.btc_balance = 0.0
    state.entry_cash_value = 0.0
    state.entry_price = None
    state.last_buy_monotonic = None
    state.next_buy_monotonic = time.monotonic() + config.buy_cooldown_seconds
    state.trade_count += 1

    messages.append(
        f"AUTO SELL | Net ${received:.2f} | Fee ${fee:.2f} | P/L {pnl:+.2f} ({pnl_pct:+.2f}%) "
        f"at effective ${execution_price:.2f} (market ${result.price:.2f}) "
        f"after a ${result.price - entry_price:.2f} rise from entry | "
        f"Cash: ${cash_before:.2f} -> ${state.cash_balance:.2f} | "
        f"Equity before sell: ${equity_before:.2f}"
    )
    messages.append(
        f"AP2 SIM | Payment Mandate created: {payment_record['payload']['mandateId']} | SIMULATED_EXECUTED"
    )
    return messages


def update_simulation(
    result: SignalResult, config: SimulationConfig, state: SimulationState
) -> list[str]:
    if not config.enabled:
        return []

    messages: list[str] = []
    now = time.monotonic()
    current_price = result.price
    previous_seen_price = state.last_seen_price
    state.last_seen_price = current_price

    if (
        state.btc_balance <= 0
        and state.cash_balance > 0
        and previous_seen_price is not None
        and now >= state.next_buy_monotonic
        and current_price <= previous_seen_price - config.drop_to_buy_usd
    ):
        if config.require_signal_confirmation and result.signal != "BUY":
            return [f"TRIGGER WAIT | BUY price trigger met, but signal is {result.signal}."]
        messages.extend(execute_ap2_buy(result, config, state, previous_seen_price))
        return messages

    if (
        state.btc_balance > 0
        and state.entry_price is not None
        and current_price >= state.entry_price + config.rise_to_sell_usd
    ):
        if config.require_signal_confirmation and result.signal != "SELL":
            return [f"TRIGGER WAIT | SELL price trigger met, but signal is {result.signal}."]
        messages.extend(execute_ap2_sell(result, config, state))

    return messages


def simulation_summary(current_price: float, state: SimulationState) -> str:
    equity = state.cash_balance + (state.btc_balance * current_price)
    unrealized = 0.0
    if state.btc_balance > 0 and state.entry_cash_value:
        unrealized = (state.btc_balance * current_price) - state.entry_cash_value

    return (
        f"SIM | Equity: ${equity:.2f} | Cash: ${state.cash_balance:.2f} | "
        f"BTC: {state.btc_balance:.8f} | Unrealized: {unrealized:+.2f} | "
        f"Realized: {state.realized_pnl:+.2f} | Trades: {state.trade_count}"
    )


def print_tracker_update(
    result: SignalResult,
    previous_price: float | None,
    simulation_state: SimulationState | None = None,
    simulation_messages: list[str] | None = None,
    status_label: str | None = None,
) -> None:
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    price_move = status_label or format_change(result.price, previous_price)
    print("-" * 100)
    print(
        f"[{timestamp}] "
        f"BTC: ${result.price:.2f} | "
        f"{price_move} | "
        f"Signal: {result.signal} | "
        f"Action: {result.execution_action} | "
        f"Confidence: {result.confidence}%"
    )
    if simulation_state is not None:
        print(simulation_summary(result.price, simulation_state))
    for message in simulation_messages or []:
        print(message)
    print("")


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
        binance_retry_count=env_int("BINANCE_RETRY_COUNT", 3),
        binance_retry_delay_seconds=env_float("BINANCE_RETRY_DELAY_SECONDS", 2.0),
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


def _run_cycle_unlocked(config: AgentConfig) -> SignalResult:
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

    if snapshot_refreshed:
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


def run_cycle(config: AgentConfig) -> SignalResult:
    # A cycle is a read-modify-write transaction over the shared state file.
    # Serializing the full operation prevents concurrent API/background cycles
    # from losing updates even though upstream requests happen between reads.
    with _STATE_LOCK:
        return _run_cycle_unlocked(config)


def run_cycle_with_retries(
    config: AgentConfig, last_result: SignalResult | None
) -> tuple[SignalResult | None, str | None]:
    attempts = max(1, config.binance_retry_count)
    last_error: str | None = None

    for attempt in range(1, attempts + 1):
        try:
            return run_cycle(config), None
        except RuntimeError as exc:
            last_error = str(exc)
            if "Binance" not in last_error and "timed out" not in last_error:
                raise

            if attempt < attempts:
                print(
                    f"Warning: {last_error}. Retrying {attempt}/{attempts - 1} "
                    f"in {config.binance_retry_delay_seconds:.1f}s..."
                )
                time.sleep(config.binance_retry_delay_seconds)

    if last_result is not None and last_error is not None:
        return last_result, f"STALE | {last_error}"

    raise RuntimeError(last_error or "Binance request failed")


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
    simulation_config = SimulationConfig()
    if not getattr(args, "once", False) and args.poll_seconds is None:
        args.poll_seconds, simulation_config = prompt_startup_mode()
    elif args.poll_seconds is None:
        args.poll_seconds = defaults.poll_seconds

    config = config_from_args(args)
    previous_price: float | None = None
    last_result: SignalResult | None = None
    simulation_state = create_simulation_state(simulation_config) if simulation_config.enabled else None
    ap2_startup_messages: list[str] = []
    if simulation_config.enabled and simulation_state is not None:
        simulation_state.active_intent_mandate, ap2_startup_messages = initialize_ap2_simulation(
            config.symbol,
            simulation_config,
        )

    try:
        print(f"Using OpenAI model: {config.openai_model}")
        print(f"Signal refresh interval: {config.signal_refresh_seconds} second(s)")
        print(f"Tracking {config.symbol} from Binance every {config.poll_seconds} second(s).")
        if simulation_config.enabled:
            print(
                "Auto simulation enabled: "
                f"buy cooldown {simulation_config.buy_cooldown_seconds} second(s), "
                f"buy after a ${simulation_config.drop_to_buy_usd:.2f} drop, "
                f"sell after a ${simulation_config.rise_to_sell_usd:.2f} rise from entry, "
                f"starting cash ${simulation_config.starting_cash:.2f}."
            )
            for line in ap2_startup_messages:
                print(line)
        print("Press Ctrl+C to stop.")
        print("")
        print_startup_status(config)

        while True:
            cycle_started = time.monotonic()
            result, warning_label = run_cycle_with_retries(config, last_result)
            if result is None:
                raise RuntimeError("Could not load tracker result.")
            if args.once:
                print_signal(result)
                return 0

            simulation_messages = []
            if simulation_state is not None:
                simulation_messages = update_simulation(result, simulation_config, simulation_state)

            print_tracker_update(
                result,
                previous_price,
                simulation_state,
                simulation_messages,
                status_label=warning_label,
            )
            previous_price = result.price
            last_result = result
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
