"""Public market-data clients. No authenticated trading endpoints are implemented."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class BinanceClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"{self.base_url}{path}?{query}",
            headers={"Accept": "application/json", "User-Agent": "btc-signal-agent/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Binance request failed with HTTP {exc.code}: {body or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Binance: {exc.reason}") from exc
        return json.loads(payload)

    def get_klines(self, symbol: str, interval: str, limit: int) -> list[list[Any]]:
        data = self._get_json(
            "/api/v3/klines", {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        )
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected Binance response: {data}")
        return data

    def get_ticker_price(self, symbol: str) -> float:
        data = self._get_json("/api/v3/ticker/price", {"symbol": symbol.upper()})
        if not isinstance(data, dict) or "price" not in data:
            raise RuntimeError(f"Unexpected Binance ticker response: {data}")
        return float(data["price"])
