from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import api_server


class ApiServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.status_path_patcher = patch.object(
            api_server,
            "AUTO_STATUS_PATH",
            Path(cls.temp_dir.name) / "auto_sim_state.json",
        )
        cls.runner_patcher = patch.object(api_server, "AUTO_RUNNER", api_server.AutoSimulationRunner())
        cls.status_path_patcher.start()
        cls.runner_patcher.start()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api_server.AgentApiHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        api_server.AUTO_RUNNER.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.runner_patcher.stop()
        cls.status_path_patcher.stop()
        cls.temp_dir.cleanup()

    def get_json(self, path: str) -> tuple[int, dict[str, object]]:
        try:
            with urllib.request.urlopen(f"{self.base_url}{path}", timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

    def post_json(
        self,
        path: str,
        payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object]]:
        body = json.dumps(payload or {}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

    def get_text(self, path: str) -> tuple[int, str]:
        try:
            with urllib.request.urlopen(f"{self.base_url}{path}", timeout=5) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, exc.read().decode("utf-8")

    def test_invalid_checkout_inputs_return_400(self) -> None:
        for payload in [
            {"maximumSpendingAmount": "NaN"},
            {"maximumSpendingAmount": None},
            {"approveCart": "false"},
            {"items": [{"name": "Book", "category": "books", "quantity": 1.9, "unitPrice": 10}]},
        ]:
            with self.subTest(payload=payload):
                status, result = self.post_json("/ap2/checkout/run", payload)
                self.assertEqual(status, 400)
                self.assertFalse(result["ok"])

    def test_nan_auto_configuration_returns_400(self) -> None:
        status, payload = self.post_json("/auto/configure?startingCash=NaN")
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_health(self) -> None:
        status, payload = self.get_json("/health")

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["service"], "btc-agent-api")
        self.assertTrue(payload["simulationOnly"])
        self.assertTrue(payload["marketDataOnly"])

    def test_auto_status(self) -> None:
        status, payload = self.get_json("/auto/status")

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIn("running", payload["auto"])
        self.assertTrue(payload["auto"]["simulationOnly"])
        self.assertTrue(payload["auto"]["marketDataOnly"])

    def test_auto_configure_valid(self) -> None:
        status, payload = self.post_json(
            "/auto/configure?pollSeconds=3&startingCash=250&buyCooldownSeconds=2"
            "&dropToBuyUsd=10&riseToSellUsd=12"
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["auto"]["pollSeconds"], 3)
        self.assertEqual(payload["auto"]["rules"]["startingCash"], 250.0)

    def test_auto_configure_invalid_query_param_returns_400(self) -> None:
        status, payload = self.post_json("/auto/configure?pollSeconds=fast")

        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("pollSeconds", payload["error"])

    def test_state(self) -> None:
        status, payload = self.get_json("/state")

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIn("state", payload)

    def test_dashboard_is_served_by_python_api(self) -> None:
        status, body = self.get_text("/dashboard")

        self.assertEqual(status, 200)
        self.assertIn("Simulation only", body)
        self.assertIn("/auto/status", body)

    def test_ap2_protocol_boundary(self) -> None:
        status, payload = self.get_json("/ap2")

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["protocol"]["implemented"])

    def test_mutating_get_is_rejected(self) -> None:
        status, payload = self.get_json("/auto/start")

        self.assertEqual(status, 405)
        self.assertFalse(payload["ok"])

    def test_configured_token_is_required_for_mutation(self) -> None:
        with patch.dict("os.environ", {"AGENT_API_TOKEN": "test-token"}):
            status, payload = self.post_json("/auto/stop")
            authorized_status, authorized_payload = self.post_json(
                "/auto/stop", headers={"Authorization": "Bearer test-token"}
            )

        self.assertEqual(status, 401)
        self.assertFalse(payload["ok"])
        self.assertEqual(authorized_status, 200)
        self.assertTrue(authorized_payload["ok"])

    def test_request_body_limit(self) -> None:
        request = urllib.request.Request(
            f"{self.base_url}/ap2/checkout/run",
            data=b"{}",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(api_server.MAX_REQUEST_BODY_BYTES + 1),
            },
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)

        with caught.exception:
            self.assertEqual(caught.exception.code, 413)

    def test_mutation_rejects_non_json_content_type(self) -> None:
        request = urllib.request.Request(
            f"{self.base_url}/auto/start",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "text/plain"},
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)

        with caught.exception:
            self.assertEqual(caught.exception.code, 415)


class ApiSecurityUnitTests(unittest.TestCase):
    def test_non_loopback_hosts_are_detected(self) -> None:
        self.assertTrue(api_server.is_loopback_host("127.0.0.1"))
        self.assertTrue(api_server.is_loopback_host("::1"))
        self.assertFalse(api_server.is_loopback_host("0.0.0.0"))

    def test_signal_config_does_not_accept_network_or_path_overrides(self) -> None:
        defaults = api_server.btc_agent.AgentConfig()
        config = api_server.build_config(
            {
                "baseUrl": ["http://127.0.0.1:9999/private"],
                "stateFile": ["../../unexpected.json"],
            }
        )

        self.assertEqual(config.base_url, defaults.base_url)
        self.assertEqual(config.state_file, defaults.state_file)

    def test_signal_config_validates_symbol_interval_and_bounds(self) -> None:
        invalid_queries = [
            {"symbol": ["../../etc/passwd"]},
            {"interval": ["forever"]},
            {"lookback": ["1000000"]},
            {"requestTimeout": ["600"]},
        ]

        for query in invalid_queries:
            with self.subTest(query=query), self.assertRaises(ValueError):
                api_server.build_config(query)


class AutoRunnerUnitTests(unittest.TestCase):
    def test_stop_persists_not_running_status(self) -> None:
        runner = api_server.AutoSimulationRunner()

        with (
            patch("api_server.btc_agent.initialize_ap2_simulation", return_value=(None, [])),
            patch.object(runner, "_run", side_effect=lambda *args: args[1].wait()),
            patch("api_server.save_auto_status") as save_status,
        ):
            runner.start()
            runner.stop()

        self.assertFalse(runner.is_running())
        self.assertFalse(save_status.call_args.args[0]["running"])

    def test_start_preserves_settings_applied_while_stopped(self) -> None:
        runner = api_server.AutoSimulationRunner()
        runner.configure(
            {
                "pollSeconds": ["2"],
                "startingCash": ["100"],
                "buyCooldownSeconds": ["2"],
                "dropToBuyUsd": ["0.01"],
                "riseToSellUsd": ["0.01"],
                "feeRateBps": ["10"],
                "slippageBps": ["2"],
                "requireSignalConfirmation": ["true"],
            }
        )

        with (
            patch("api_server.btc_agent.initialize_ap2_simulation", return_value=(None, [])),
            patch.object(runner, "_run", return_value=None),
            patch("api_server.save_auto_status"),
        ):
            runner.start()
            if runner.thread:
                runner.thread.join(timeout=1)

        self.assertEqual(runner.config.poll_seconds, 2)
        self.assertEqual(runner.simulation_config.starting_cash, 100.0)
        self.assertEqual(runner.simulation_config.buy_cooldown_seconds, 2)
        self.assertEqual(runner.simulation_config.drop_to_buy_usd, 0.01)
        self.assertEqual(runner.simulation_config.rise_to_sell_usd, 0.01)
        self.assertEqual(runner.simulation_config.fee_rate_bps, 10.0)
        self.assertEqual(runner.simulation_config.slippage_bps, 2.0)
        self.assertTrue(runner.simulation_config.require_signal_confirmation)

if __name__ == "__main__":
    unittest.main()
