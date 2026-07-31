from __future__ import annotations

import contextlib
import hmac
import json
import os
import sys
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import ap2_sim
import btc_agent


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
API_VERSION = "2026-07-31-hardened-v3"
SIMULATION_ONLY = True
MARKET_DATA_ONLY = True
AUTO_STATUS_PATH = BASE_DIR / "auto_sim_state.json"
DASHBOARD_PATH = BASE_DIR / "dashboard.html"
DASHBOARD_CSS_PATH = BASE_DIR / "dashboard.css"
WEB_PUBLIC_DIR = BASE_DIR / "web" / "public"
WEB_APP_DIR = BASE_DIR / "web" / "app"
MAX_REQUEST_BODY_BYTES = 64 * 1024
MUTATING_PATHS = {
    "/signal",
    "/auto/start",
    "/auto/stop",
    "/auto/configure",
    "/ap2/checkout/demo",
    "/ap2/checkout/run",
}


def api_token() -> str:
    return btc_agent.env_str("AGENT_API_TOKEN", "")


def configured_cors_origin() -> str:
    return btc_agent.env_str("AGENT_CORS_ORIGIN", "")


def is_loopback_host(host: str) -> bool:
    return host.strip().lower() in {"127.0.0.1", "localhost", "::1"}


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary_path, path)
    finally:
        with contextlib.suppress(OSError):
            temporary_path.unlink()


def read_json_file(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def normalize_checkout_items(raw_items: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        raise ValueError("items must be a list.")

    items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise ValueError("Each item must be an object.")
        items.append(
            {
                "name": str(raw_item.get("name", "")).strip(),
                "category": str(raw_item.get("category", "")).strip(),
                "quantity": int(raw_item.get("quantity", 1)),
                "unitPrice": float(raw_item.get("unitPrice", 0.0)),
            }
        )
    return items


def normalize_categories(raw_categories: Any) -> list[str]:
    if isinstance(raw_categories, str):
        return [category.strip() for category in raw_categories.split(",") if category.strip()]
    if isinstance(raw_categories, list):
        return [str(category).strip() for category in raw_categories if str(category).strip()]
    raise ValueError("allowedCategories must be a list or comma-separated string.")


def run_checkout_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return ap2_sim.run_checkout_scenario(
        user_id=str(payload.get("userId", "web_user")).strip() or "web_user",
        merchant_id=str(payload.get("merchantId", "web_merchant")).strip() or "web_merchant",
        agent_id=str(payload.get("agentId", "web_agent")).strip() or "web_agent",
        maximum_spending_amount=float(payload.get("maximumSpendingAmount", 100.0)),
        currency=str(payload.get("currency", "USD")).strip().upper() or "USD",
        allowed_categories=normalize_categories(payload.get("allowedCategories", ["books", "software"])),
        items=normalize_checkout_items(payload.get("items", [])),
        human_approval_required=bool(payload.get("humanApprovalRequired", False)),
        approve_cart=bool(payload.get("approveCart", False)),
        human_present=bool(payload.get("humanPresent", False)),
        payment_method=str(payload.get("paymentMethod", "simulated_card")).strip() or "simulated_card",
    )


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

    symbol = get_string("symbol", defaults.symbol).upper()
    if not symbol.isalnum() or not 5 <= len(symbol) <= 20:
        raise ValueError("symbol must be 5-20 letters or numbers.")
    interval = get_string("interval", defaults.interval)
    allowed_intervals = {
        "1s", "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h",
        "6h", "8h", "12h", "1d", "3d", "1w", "1M",
    }
    if interval not in allowed_intervals:
        raise ValueError("interval is not supported by Binance.")

    args.symbol = symbol
    args.interval = interval
    args.lookback = query_int(query, "lookback", defaults.lookback, 60, 1000)
    args.poll_seconds = query_int(query, "pollSeconds", defaults.poll_seconds, 1, 3600)
    args.request_timeout = query_float(query, "requestTimeout", defaults.request_timeout, 1.0, 60.0)
    args.buy_threshold = query_int(query, "buyThreshold", defaults.buy_threshold, 1, 20)
    args.sell_threshold = query_int(query, "sellThreshold", defaults.sell_threshold, 1, 20)
    # Network destinations and filesystem paths are environment/operator
    # configuration, never caller-controlled API parameters.
    args.base_url = defaults.base_url
    args.state_file = defaults.state_file
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
        atomic_write_json(AUTO_STATUS_PATH, payload)
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
            "simulationOnly": SIMULATION_ONLY,
            "marketDataOnly": MARKET_DATA_ONLY,
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
        allowed_origin = configured_cors_origin()
        request_origin = self.headers.get("Origin", "")
        if allowed_origin and hmac.compare_digest(request_origin, allowed_origin):
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        query = parse_qs(parsed_url.query)

        try:
            if parsed_url.path in MUTATING_PATHS:
                self.send_json(
                    {"ok": False, "error": "Method not allowed; use POST."},
                    status=405,
                    extra_headers={"Allow": "POST"},
                )
                return
            if parsed_url.path in {"/", "/dashboard"}:
                self.send_dashboard()
                return
            if parsed_url.path == "/dashboard.css":
                self.send_file(DASHBOARD_CSS_PATH, "text/css; charset=utf-8")
                return
            if parsed_url.path == "/logo.png":
                self.send_file(WEB_PUBLIC_DIR / "logo.png", "image/png")
                return
            if parsed_url.path == "/icon.png":
                self.send_file(WEB_APP_DIR / "icon.png", "image/png")
                return
            if parsed_url.path == "/health":
                self.send_json(
                    {
                        "ok": True,
                        "service": "btc-agent-api",
                        "apiVersion": API_VERSION,
                        "simulationOnly": SIMULATION_ONLY,
                        "marketDataOnly": MARKET_DATA_ONLY,
                    }
                )
                return
            if parsed_url.path == "/auto/status":
                self.send_json({"ok": True, "auto": AUTO_RUNNER.status()})
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
                        "protocol": ap2_sim.PROTOCOL_ALIGNMENT,
                        "usingDefaultSimulationSecret": ap2_sim.using_default_sim_secret(),
                        "activeIntentMandate": read_json_file(ap2_sim.ACTIVE_INTENT_MANDATE_PATH, {}),
                        "operations": audit_events,
                        "auditEvents": audit_events,
                    }
                )
                return
            self.send_json({"ok": False, "error": "Not found"}, status=404)
        except ValueError as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:  # noqa: BLE001
            self.send_internal_error(exc)

    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)
        query = parse_qs(parsed_url.query)

        try:
            if parsed_url.path not in MUTATING_PATHS:
                self.send_json({"ok": False, "error": "Not found"}, status=404)
                return
            if not self.has_json_content_type():
                self.send_json(
                    {"ok": False, "error": "Content-Type must be application/json."},
                    status=415,
                )
                return
            if not self.is_authorized():
                self.send_json(
                    {"ok": False, "error": "Unauthorized."},
                    status=401,
                    extra_headers={"WWW-Authenticate": "Bearer"},
                )
                return

            content_length = self.request_content_length()
            raw_body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
            payload = json.loads(raw_body)
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object.")

            if parsed_url.path == "/signal":
                result = btc_agent.run_cycle(build_config(query))
                self.send_json({"ok": True, "signal": asdict(result)})
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
            if parsed_url.path == "/ap2/checkout/demo":
                self.send_json({"ok": True, "checkout": ap2_sim.run_default_payment_chain_simulation()})
                return
            if parsed_url.path == "/ap2/checkout/run":
                self.send_json({"ok": True, "checkout": run_checkout_payload(payload)})
                return

            self.send_json({"ok": False, "error": "Not found"}, status=404)
        except RequestHandled:
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:  # noqa: BLE001
            self.send_internal_error(exc)

    def request_content_length(self) -> int:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            content_length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Content-Length must be a whole number.") from exc
        if content_length < 0:
            raise ValueError("Content-Length cannot be negative.")
        if content_length > MAX_REQUEST_BODY_BYTES:
            self.send_json({"ok": False, "error": "Request body is too large."}, status=413)
            raise RequestHandled()
        return content_length

    def has_json_content_type(self) -> bool:
        content_type = self.headers.get("Content-Type", "")
        media_type = content_type.partition(";")[0].strip().lower()
        return media_type == "application/json"

    def is_authorized(self) -> bool:
        expected_token = api_token()
        if not expected_token:
            return True
        authorization = self.headers.get("Authorization", "")
        scheme, separator, supplied_token = authorization.partition(" ")
        return bool(
            separator
            and scheme.lower() == "bearer"
            and hmac.compare_digest(supplied_token.strip(), expected_token)
        )

    def send_internal_error(self, exc: Exception) -> None:
        error_id = uuid4().hex[:12]
        print(f"API error {error_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
        self.send_json(
            {"ok": False, "error": "Internal server error.", "errorId": error_id},
            status=500,
        )

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

    def send_file(self, path: Path, content_type: str) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self.send_json({"ok": False, "error": f"{path.name} is missing"}, status=404)
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(
        self,
        payload: dict[str, Any],
        status: int = 200,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)


class RequestHandled(Exception):
    """Stops request processing after a response has already been sent."""


def main() -> int:
    host = btc_agent.env_str("AGENT_API_HOST", DEFAULT_HOST)
    port = btc_agent.env_int("AGENT_API_PORT", DEFAULT_PORT)
    if not is_loopback_host(host) and not api_token():
        print("Refusing non-loopback API binding without AGENT_API_TOKEN.", file=sys.stderr)
        return 2
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
