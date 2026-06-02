from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import ap2_sim
import btc_agent


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
API_VERSION = "2026-04-26-auto-runner-v2"
AUTO_STATUS_PATH = BASE_DIR / "auto_sim_state.json"
DASHBOARD_PATH = BASE_DIR / "dashboard.html"


def read_json_file(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def read_audit_log(limit: int) -> list[dict[str, Any]]:
    operations_payload = read_json_file(ap2_sim.AP2_OPERATIONS_LOG_PATH, {})
    operations = operations_payload.get("operations") if isinstance(operations_payload, dict) else None
    if isinstance(operations, list):
        return [event for event in operations[-limit:] if isinstance(event, dict)]

    path = ap2_sim.AP2_SIMULATION_LOG_PATH
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    events: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def env_bool(name: str, default: bool) -> bool:
    value = btc_agent.env_str(name, str(default)).lower()
    return value in {"1", "true", "yes", "on"}


def build_config(query: dict[str, list[str]]) -> btc_agent.AgentConfig:
    defaults = btc_agent.AgentConfig()
    parser = btc_agent.build_parser(defaults, include_once=False)
    args = parser.parse_args([])

    def get_string(name: str, default: str) -> str:
        values = query.get(name)
        return values[0] if values and values[0] else default

    args.symbol = get_string("symbol", defaults.symbol).upper()
    args.interval = get_string("interval", defaults.interval)
    args.lookback = int(get_string("lookback", str(defaults.lookback)))
    args.poll_seconds = int(get_string("pollSeconds", str(defaults.poll_seconds)))
    args.base_url = get_string("baseUrl", defaults.base_url)
    args.request_timeout = float(get_string("requestTimeout", str(defaults.request_timeout)))
    args.buy_threshold = int(get_string("buyThreshold", str(defaults.buy_threshold)))
    args.sell_threshold = int(get_string("sellThreshold", str(defaults.sell_threshold)))
    args.state_file = get_string("stateFile", defaults.state_file)
    return btc_agent.config_from_args(args)


def build_auto_config() -> tuple[btc_agent.AgentConfig, btc_agent.SimulationConfig]:
    poll_seconds = btc_agent.env_int("AUTO_SIM_POLL_SECONDS", 5)
    config = btc_agent.AgentConfig(
        poll_seconds=poll_seconds,
        signal_refresh_seconds=btc_agent.env_int("AUTO_SIM_SIGNAL_REFRESH_SECONDS", poll_seconds),
    )
    simulation_config = btc_agent.SimulationConfig(
        enabled=True,
        buy_cooldown_seconds=btc_agent.env_int("AUTO_SIM_BUY_COOLDOWN_SECONDS", 5),
        drop_to_buy_usd=btc_agent.env_float("AUTO_SIM_DROP_TO_BUY_USD", 1.0),
        rise_to_sell_usd=btc_agent.env_float("AUTO_SIM_RISE_TO_SELL_USD", 1.0),
        starting_cash=btc_agent.env_float("AUTO_SIM_STARTING_CASH", 500.0),
    )
    return config, simulation_config


def query_value(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if not values or not values[0]:
        return None
    return values[0]


def query_int(query: dict[str, list[str]], name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = query_value(query, name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a whole number.") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value


def query_float(query: dict[str, list[str]], name: str, default: float, minimum: float, maximum: float) -> float:
    raw_value = query_value(query, name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number.") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}.")
    return value


def build_auto_config_from_query(
    query: dict[str, list[str]],
    current_config: btc_agent.AgentConfig,
    current_simulation_config: btc_agent.SimulationConfig,
) -> tuple[btc_agent.AgentConfig, btc_agent.SimulationConfig]:
    config = btc_agent.AgentConfig(
        symbol=current_config.symbol,
        interval=current_config.interval,
        lookback=current_config.lookback,
        poll_seconds=query_int(query, "pollSeconds", current_config.poll_seconds, 1, 3600),
        base_url=current_config.base_url,
        request_timeout=current_config.request_timeout,
        buy_threshold=current_config.buy_threshold,
        sell_threshold=current_config.sell_threshold,
        state_file=current_config.state_file,
        openai_api_key=current_config.openai_api_key,
        openai_model=current_config.openai_model,
        openai_base_url=current_config.openai_base_url,
        openai_timeout=current_config.openai_timeout,
        signal_refresh_seconds=query_int(query, "pollSeconds", current_config.poll_seconds, 1, 3600),
        binance_retry_count=current_config.binance_retry_count,
        binance_retry_delay_seconds=current_config.binance_retry_delay_seconds,
    )
    simulation_config = btc_agent.SimulationConfig(
        enabled=True,
        buy_cooldown_seconds=query_int(
            query,
            "buyCooldownSeconds",
            current_simulation_config.buy_cooldown_seconds,
            0,
            86400,
        ),
        drop_to_buy_usd=query_float(
            query,
            "dropToBuyUsd",
            current_simulation_config.drop_to_buy_usd,
            0.01,
            100000.0,
        ),
        rise_to_sell_usd=query_float(
            query,
            "riseToSellUsd",
            current_simulation_config.rise_to_sell_usd,
            0.01,
            100000.0,
        ),
        starting_cash=query_float(
            query,
            "startingCash",
            current_simulation_config.starting_cash,
            1.0,
            1000.0,
        ),
    )
    return config, simulation_config


def simulation_state_to_dict(state: btc_agent.SimulationState | None, current_price: float | None) -> dict[str, Any]:
    if state is None:
        return {}

    price = current_price or state.entry_price or state.last_seen_price or 0.0
    equity = state.cash_balance + (state.btc_balance * price)
    unrealized = 0.0
    if state.btc_balance > 0 and state.entry_cash_value:
        unrealized = (state.btc_balance * price) - state.entry_cash_value

    return {
        "cashBalance": round(state.cash_balance, 2),
        "btcBalance": state.btc_balance,
        "equity": round(equity, 2),
        "entryPrice": state.entry_price,
        "entryCashValue": round(state.entry_cash_value, 2),
        "realizedPnl": round(state.realized_pnl, 2),
        "unrealizedPnl": round(unrealized, 2),
        "tradeCount": state.trade_count,
        "lastSeenPrice": state.last_seen_price,
    }


def save_auto_status(payload: dict[str, Any]) -> None:
    try:
        AUTO_STATUS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        return


class AutoSimulationRunner:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.generation = 0
        self.config, self.simulation_config = build_auto_config()
        self.simulation_state: btc_agent.SimulationState | None = None
        self.previous_price: float | None = None
        self.last_result: btc_agent.SignalResult | None = None
        self.last_messages: list[str] = []
        self.last_error: str | None = None
        self.last_tick_utc = ""
        self.started_at_utc = ""

    def start(
        self,
        config: btc_agent.AgentConfig | None = None,
        simulation_config: btc_agent.SimulationConfig | None = None,
    ) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return

            self.generation += 1
            generation = self.generation
            self.stop_event = threading.Event()
            stop_event = self.stop_event
            if config is not None:
                self.config = config
            elif simulation_config is None:
                self.config, self.simulation_config = build_auto_config()
            if simulation_config is not None:
                self.simulation_config = simulation_config
            self.simulation_state = btc_agent.create_simulation_state(self.simulation_config)
            run_config = self.config
            run_simulation_config = self.simulation_config
            run_simulation_state = self.simulation_state
            self.previous_price = None
            self.last_result = None
            self.last_messages = []
            self.last_error = None
            self.last_tick_utc = ""
            self.started_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

            try:
                intent_record, startup_messages = btc_agent.initialize_ap2_simulation(
                    run_config.symbol,
                    run_simulation_config,
                )
                run_simulation_state.active_intent_mandate = intent_record
                self.last_messages = startup_messages
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)

            self.thread = threading.Thread(
                target=self._run,
                args=(generation, stop_event, run_config, run_simulation_config, run_simulation_state),
                name="auto-simulation-runner",
                daemon=True,
            )
            self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def configure(self, query: dict[str, list[str]]) -> dict[str, Any]:
        with self.lock:
            config, simulation_config = build_auto_config_from_query(query, self.config, self.simulation_config)
            thread = self.thread
            was_running = bool(thread and thread.is_alive())
            self.stop_event.set()
            self.generation += 1

        if thread and thread.is_alive():
            thread.join(timeout=5)

        self.thread = None
        self.config = config
        self.simulation_config = simulation_config
        if was_running:
            self.start(config, simulation_config)
        else:
            self.simulation_state = btc_agent.create_simulation_state(simulation_config)
            self.last_result = None
            self.last_messages = ["Auto simulation settings saved. Start auto to begin with the new rules."]
            self.last_error = None
            self.last_tick_utc = ""
            self.started_at_utc = ""

        return self.status()

    def is_running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def _run(
        self,
        generation: int,
        stop_event: threading.Event,
        config: btc_agent.AgentConfig,
        simulation_config: btc_agent.SimulationConfig,
        simulation_state: btc_agent.SimulationState,
    ) -> None:
        last_result: btc_agent.SignalResult | None = None
        while not stop_event.is_set():
            started = time.monotonic()
            try:
                result, warning = btc_agent.run_cycle_with_retries(config, last_result)
                if result is None:
                    raise RuntimeError("Agent cycle returned no result.")

                messages: list[str] = []
                messages = btc_agent.update_simulation(result, simulation_config, simulation_state)
                if warning:
                    messages = [warning] + messages

                with self.lock:
                    if generation != self.generation:
                        return
                    last_result = result
                    self.last_result = result
                    self.last_messages = messages
                    self.last_error = None
                    self.last_tick_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    self.previous_price = result.price
                    save_auto_status(self.status_locked())
            except Exception as exc:  # noqa: BLE001
                with self.lock:
                    if generation != self.generation:
                        return
                    self.last_error = str(exc)
                    self.last_tick_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    save_auto_status(self.status_locked())

            sleep_seconds = max(0.5, config.poll_seconds - (time.monotonic() - started))
            stop_event.wait(sleep_seconds)

    def status(self) -> dict[str, Any]:
        with self.lock:
            return self.status_locked()

    def status_locked(self) -> dict[str, Any]:
        current_price = self.last_result.price if self.last_result else None
        payload = {
            "apiVersion": API_VERSION,
            "running": self.is_running(),
            "startedAtUtc": self.started_at_utc,
            "lastTickUtc": self.last_tick_utc,
            "lastError": self.last_error,
            "pollSeconds": self.config.poll_seconds,
            "rules": {
                "startingCash": self.simulation_config.starting_cash,
                "buyCooldownSeconds": self.simulation_config.buy_cooldown_seconds,
                "dropToBuyUsd": self.simulation_config.drop_to_buy_usd,
                "riseToSellUsd": self.simulation_config.rise_to_sell_usd,
            },
            "signal": asdict(self.last_result) if self.last_result else None,
            "simulation": simulation_state_to_dict(self.simulation_state, current_price),
            "messages": self.last_messages,
        }
        return payload


AUTO_RUNNER = AutoSimulationRunner()


class AgentApiHandler(BaseHTTPRequestHandler):
    server_version = "BTCAgentAPI/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        query = parse_qs(parsed_url.query)

        try:
            if parsed_url.path in {"/", "/dashboard"}:
                self.send_dashboard()
                return
            if parsed_url.path == "/health":
                self.send_json({"ok": True, "service": "btc-agent-api", "apiVersion": API_VERSION})
                return
            if parsed_url.path == "/auto/start":
                AUTO_RUNNER.start()
                self.send_json({"ok": True, "auto": AUTO_RUNNER.status()})
                return
            if parsed_url.path == "/auto/stop":
                AUTO_RUNNER.stop()
                self.send_json({"ok": True, "auto": AUTO_RUNNER.status()})
                return
            if parsed_url.path == "/auto/configure":
                self.send_json({"ok": True, "auto": AUTO_RUNNER.configure(query)})
                return
            if parsed_url.path == "/auto/status":
                self.send_json({"ok": True, "auto": AUTO_RUNNER.status()})
                return
            if parsed_url.path == "/signal":
                result = btc_agent.run_cycle(build_config(query))
                self.send_json({"ok": True, "signal": asdict(result)})
                return
            if parsed_url.path == "/state":
                state_path = BASE_DIR / btc_agent.AgentConfig().state_file
                self.send_json({"ok": True, "state": read_json_file(state_path, {})})
                return
            if parsed_url.path == "/ap2":
                limit = int(query.get("limit", ["20"])[0])
                audit_events = read_audit_log(max(1, min(limit, 100)))
                self.send_json(
                    {
                        "ok": True,
                        "activeIntentMandate": read_json_file(ap2_sim.ACTIVE_INTENT_MANDATE_PATH, {}),
                        "operations": audit_events,
                        "auditEvents": audit_events,
                    }
                )
                return

            self.send_json({"ok": False, "error": "Not found"}, status=404)
        except Exception as exc:  # noqa: BLE001
            self.send_json({"ok": False, "error": str(exc)}, status=500)

    def send_dashboard(self) -> None:
        try:
            body = DASHBOARD_PATH.read_bytes()
        except OSError:
            self.send_json({"ok": False, "error": "dashboard.html is missing"}, status=500)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    host = btc_agent.env_str("AGENT_API_HOST", DEFAULT_HOST)
    port = btc_agent.env_int("AGENT_API_PORT", DEFAULT_PORT)
    if env_bool("AUTO_SIM_ENABLED", True):
        AUTO_RUNNER.start()
    server = ThreadingHTTPServer((host, port), AgentApiHandler)
    print(f"BTC agent API listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
