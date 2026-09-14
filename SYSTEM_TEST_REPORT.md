# System test report — 2026-09-14

## Result

All 37 end-to-end checks, 53 Python tests, and four frontend contract tests passed. Python compilation, installed Python dependency consistency (`pip check`), frontend lint, TypeScript validation and the production Next.js build passed.

## End-to-end coverage

`system_test.py` starts the actual Python API and production Next.js server on loopback, with temporary state and mandate storage and a local HTTP Binance fixture. It shuts down its processes afterward. It checks:

- Health, standalone dashboard HTML, state, auto status and audit endpoints.
- Unknown routes, POST-only mutations, invalid authentication, malformed JSON and non-object bodies.
- Market data over HTTP, rule-based signal generation and persistence.
- Configure while stopped, start, background ticks, buy/sell with real AP2 simulation signing and validation, configure while running, and stop.
- Valid checkout, budget rejection, category rejection, missing approval rejection, approved checkout and the built-in checkout demo.
- Forty concurrent status requests.
- Agent `--once`, shopping demo and backtest command-line execution.
- Production dashboard HTML and Next.js proxy reads, signal generation, checkout and forwarding of validation errors.

The first trading probe used a fixed 5.5-second wait and observed only one completed trade. Replacing this timing assumption with polling for at least two trades, bounded at 30 seconds, passed. This was a test synchronization issue; no application code was changed in this testing turn.

Detailed outcomes and the observed simulation balances are in `system_test_results.json`. Rerun using `.\.venv\Scripts\python.exe system_test.py` after building `web`. Ports 8876 and 3301 must be free.

## External connectivity

A separate read-only request to the real Binance endpoint successfully returned a positive BTCUSDT ticker price and 60 15-minute candles. The end-to-end trading tests use controlled prices so their expected transitions are repeatable.

## Limits

- Browser automation was unavailable: the browser inventory was empty and creating an in-app browser returned `Browser is not available: iab`. HTML serving and HTTP proxy behavior were tested, but client-side hydration, button interaction, responsive layout and browser rendering were not verified.
- `docker` was not available on PATH, so container startup and Compose behavior were not executed.
- Live OpenAI inference was not exercised. Structured-response and fallback behavior are covered with mocked responses in the Python suite.
- Long-running operation, restart persistence across independent server launches, launcher interaction and sustained load were not exhaustively tested.

These results establish that the exercised backend, CLI and server-side web flows pass; they do not imply that every possible software behavior has been verified.
