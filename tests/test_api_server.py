from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import api_server


class ApiServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
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

    def get_json(self, path: str) -> tuple[int, dict[str, object]]:
        try:
            with urllib.request.urlopen(f"{self.base_url}{path}", timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

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
        status, payload = self.get_json(
            "/auto/configure?pollSeconds=3&startingCash=250&buyCooldownSeconds=2"
            "&dropToBuyUsd=10&riseToSellUsd=12"
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["auto"]["pollSeconds"], 3)
        self.assertEqual(payload["auto"]["rules"]["startingCash"], 250.0)

    def test_auto_configure_invalid_query_param_returns_400(self) -> None:
        status, payload = self.get_json("/auto/configure?pollSeconds=fast")

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

    def get_text(self, path: str) -> tuple[int, str]:
        try:
            with urllib.request.urlopen(f"{self.base_url}{path}", timeout=5) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, exc.read().decode("utf-8")


if __name__ == "__main__":
    unittest.main()
