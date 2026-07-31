from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import btc_agent


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, payload: dict[str, object] | str) -> None:
        self.body = payload if isinstance(payload, str) else json.dumps(payload)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body.encode("utf-8")


def response_payload(text: str) -> dict[str, object]:
    return {
        "output": [
            {
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                    }
                ]
            }
        ]
    }


def sample_snapshot() -> btc_agent.MarketSnapshot:
    return btc_agent.MarketSnapshot(
        symbol="BTCUSDT",
        interval="15m",
        live_price=65000.0,
        candle_close_price=64950.0,
        rsi=52.0,
        ema_fast=65010.0,
        ema_mid=64900.0,
        ema_slow=64800.0,
        macd_histogram=12.5,
        atr=500.0,
        bullish_score=3,
        bearish_score=1,
        reasons=["Trend is constructive."],
    )


class OpenAIClientTests(unittest.TestCase):
    def make_client(self) -> btc_agent.OpenAIClient:
        return btc_agent.OpenAIClient(
            api_key="test-key",
            base_url="https://example.test/v1/responses",
            model="test-model",
            timeout=1.0,
        )

    def test_extract_response_text(self) -> None:
        self.assertEqual(
            btc_agent.extract_response_text(response_payload('{"signal":"HOLD"}')),
            '{"signal":"HOLD"}',
        )

    def test_get_signal_accepts_structured_json_only(self) -> None:
        payload = response_payload(
            json.dumps(
                {
                    "signal": "BUY",
                    "confidence": 81,
                    "reasons": ["Momentum improved.", "Risk remains bounded."],
                }
            )
        )
        with patch("urllib.request.urlopen", return_value=FakeResponse(payload)):
            signal, confidence, reasons = self.make_client().get_signal(sample_snapshot(), btc_agent.AgentState())

        self.assertEqual(signal, "BUY")
        self.assertEqual(confidence, 81)
        self.assertEqual(reasons, ["Momentum improved.", "Risk remains bounded."])

    def test_get_signal_invalid_json_raises(self) -> None:
        with patch("urllib.request.urlopen", return_value=FakeResponse(response_payload("not json"))):
            with self.assertRaisesRegex(RuntimeError, "invalid JSON"):
                self.make_client().get_signal(sample_snapshot(), btc_agent.AgentState())

    def test_get_signal_missing_fields_falls_back_cautiously(self) -> None:
        with patch("urllib.request.urlopen", return_value=FakeResponse(response_payload("{}"))):
            signal, confidence, reasons = self.make_client().get_signal(sample_snapshot(), btc_agent.AgentState())

        self.assertEqual(signal, "HOLD")
        self.assertEqual(confidence, 50)
        self.assertTrue(reasons)

    def test_get_signal_invalid_signal_value_becomes_hold(self) -> None:
        payload = response_payload(json.dumps({"signal": "MOON", "confidence": 99, "reasons": ["Bad value."]}))
        with patch("urllib.request.urlopen", return_value=FakeResponse(payload)):
            signal, confidence, reasons = self.make_client().get_signal(sample_snapshot(), btc_agent.AgentState())

        self.assertEqual(signal, "HOLD")
        self.assertEqual(confidence, 99)
        self.assertEqual(reasons, ["Bad value."])

    def test_request_uses_strict_json_schema_output(self) -> None:
        captured_payload: dict[str, object] = {}

        def fake_urlopen(request: object, timeout: float) -> FakeResponse:
            del timeout
            captured_payload.update(json.loads(request.data.decode("utf-8")))
            return FakeResponse(response_payload(json.dumps({"signal": "HOLD", "confidence": 50, "reasons": ["OK"]})))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            self.make_client().get_signal(sample_snapshot(), btc_agent.AgentState())

        text_format = captured_payload["text"]["format"]
        self.assertEqual(text_format["type"], "json_schema")
        self.assertTrue(text_format["strict"])


class RuntimeFallbackTests(unittest.TestCase):
    def test_run_cycle_uses_rule_based_fallback_without_openai_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot = sample_snapshot()
            snapshot.bullish_score = 5
            config = btc_agent.AgentConfig(
                state_file=str(Path(temp_dir) / "agent_state.json"),
                openai_api_key="",
            )

            with patch("btc_agent.get_market_snapshot", return_value=(snapshot, True)):
                result = btc_agent.run_cycle(config)

        self.assertEqual(result.signal, "BUY")
        self.assertTrue(result.reasons[0].startswith("Using rule-based fallback because OPENAI_API_KEY is missing."))

    def test_run_cycle_with_retries_returns_stale_result_after_binance_failure(self) -> None:
        last_result = btc_agent.build_signal_result(
            sample_snapshot(),
            btc_agent.AgentState(),
            "HOLD",
            50,
            ["Cached result."],
        )
        config = btc_agent.AgentConfig(binance_retry_count=2, binance_retry_delay_seconds=0)

        with patch("btc_agent.run_cycle", side_effect=RuntimeError("Could not reach Binance: timed out")):
            result, warning = btc_agent.run_cycle_with_retries(config, last_result)

        self.assertIs(result, last_result)
        self.assertIsNotNone(warning)
        self.assertTrue(warning.startswith("STALE |"))


class SecretSafetyTests(unittest.TestCase):
    def test_example_env_contains_placeholder_not_openai_secret(self) -> None:
        example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

        self.assertIn("OPENAI_API_KEY=your_api_key_here", example)
        self.assertNotIn("sk-proj-", example)

    def test_source_does_not_load_example_env(self) -> None:
        source = (PROJECT_ROOT / "btc_agent.py").read_text(encoding="utf-8")

        self.assertNotIn('load_local_env(Path(__file__).with_name(".env.example"))', source)


class StatePersistenceTests(unittest.TestCase):
    def test_save_state_atomically_replaces_file_without_temp_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "nested" / "agent_state.json"
            expected = btc_agent.AgentState(last_signal="BUY", last_confidence=77)

            btc_agent.save_state(state_path, expected)
            loaded = btc_agent.load_state(state_path)

            self.assertEqual(loaded.last_signal, "BUY")
            self.assertEqual(loaded.last_confidence, 77)
            self.assertEqual(list(state_path.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
