# BTC Binance Signal Agent

A Python-based trading signal agent that watches `BTCUSDT` on Binance in real time, computes technical indicators (RSI, EMA, MACD, ATR), and queries OpenAI for a `BUY`, `SELL`, or `HOLD` recommendation. Includes a built-in web dashboard, a local JSON API, an auto-simulation mode, and an AP2-inspired mandate audit trail.

> **This is a simulation only. No real orders are placed and no real money moves.**

---

## Project Structure

```
python-ai-agent-buy-sell/
├── btc_agent.py            # Core agent: market data, indicators, OpenAI signal, simulation engine
├── api_server.py           # Local HTTP API (port 8765) + dashboard server
├── ap2_sim.py              # AP2-inspired mandate creation, signing, and audit logging
├── dashboard.html          # Standalone web dashboard (served by api_server.py)
├── web/                    # Next.js dashboard (optional development UI)
├── agent_state.json        # Persisted agent position state (FLAT / LONG)
├── auto_sim_state.json     # Latest auto-simulation snapshot (written each tick)
├── ap2_mandates/           # Active intent mandate JSON
├── ap2_logs/               # AP2 audit log files
├── .env                    # Your local secrets (not committed)
├── .env.example            # Example environment variable template
├── START_DASHBOARD.cmd     # One-click dashboard launcher (Windows)
├── start_dashboard.bat     # Alternative double-click launcher (Windows)
├── start_dashboard.ps1     # PowerShell launcher with optional port arguments
├── start_web_app.bat       # Console agent launcher with menu (Windows)
└── start_web_app.ps1       # PowerShell console agent launcher
```

---

## Requirements

- Python 3.11 or later
- `cryptography` for the ECDSA mandate-signing simulation
- An [OpenAI API key](https://platform.openai.com/account/api-keys)
- Internet access to reach `api.binance.com`

---

## First-Time Setup

1. Create a `.env` file in the project root (copy from `.env.example`):

```env
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4.1-nano
BINANCE_SYMBOL=BTCUSDT
BINANCE_INTERVAL=15m
BINANCE_LOOKBACK=250
OPENAI_TIMEOUT=20
```

2. If no `.env` is found, the PowerShell launcher will prompt you for your key and save it automatically.

---

## Quickstart

### Windows — double-click launcher

```
start_web_app.bat
```

Choose an update speed from the menu:

| Option | Speed |
|--------|-------|
| `1` | Every 1 second |
| `2` | Every 10 seconds |
| `3` | Every 1 minute |
| `5` | Auto buy/sell simulation |

If you choose **5 (Auto simulation)**, you will be asked:

- Starting cash (up to `$1000.00`)
- Buy cooldown (seconds before another buy is allowed)
- Buy trigger (USD drop from the last observed price)
- Sell trigger (USD rise from the simulated entry price)

### Windows — PowerShell

```powershell
.\start_web_app.ps1
```

### Linux / macOS — direct Python

```bash
python btc_agent.py --poll-seconds 10
```

Run once and exit:

```bash
python btc_agent.py --once
```

---

## Web Dashboard

The dashboard is the easiest way to monitor and control the simulation.

**Start the dashboard:**

```cmd
START_DASHBOARD.cmd
```

Then open **http://127.0.0.1:8765** in your browser.

The dashboard is served directly by `api_server.py` from `dashboard.html` — no Node.js or `npm` is needed at runtime.

**With custom ports (PowerShell):**

```powershell
powershell -ExecutionPolicy Bypass -File .\start_dashboard.ps1 -ApiPort 8765 -WebPort 3000
```

### Dashboard simulation defaults

| Setting | Default | Range |
|---------|---------|-------|
| Starting cash | `$500.00` | `$1.00` – `$1000.00` |
| Loop interval | 5 seconds | 1 – 3600 seconds |
| Buy cooldown | 5 seconds | 0 – 86400 seconds |
| Buy trigger (drop) | `$1.00` | `$0.01` – `$100000.00` |
| Sell trigger (rise) | `$1.00` | `$0.01` – `$100000.00` |

Press **Apply** on the dashboard to restart the simulation with new values.

---

## Local JSON API

`api_server.py` starts a `ThreadingHTTPServer` on `http://127.0.0.1:8765`.

| Endpoint | Description |
|----------|-------------|
| `GET /` or `/dashboard` | Serves `dashboard.html` |
| `GET /health` | Returns `{"ok": true}` with API version |
| `GET /signal` | Runs one agent cycle and returns the signal result |
| `GET /state` | Returns the current `agent_state.json` contents |
| `GET /auto/start` | Starts the background auto-simulation runner |
| `GET /auto/stop` | Stops the auto-simulation runner |
| `GET /auto/status` | Returns current simulation state and last signal |
| `GET /auto/configure` | Reconfigures and restarts the runner with query params |
| `GET /ap2` | Returns the active simulated mandate, audit log entries, and simulation-only protocol metadata |

### ECDSA shopping mandate demo

`ap2_sim.py` also includes a generic user/merchant/agent checkout-chain simulation:

```bash
python ap2_sim.py --shopping-demo
```

For a custom interactive scenario:

```bash
python ap2_sim.py --interactive-checkout
```

The demo registers a user, merchant, and agent, generates ECDSA P-256 key pairs, creates signed Intent/Cart/Payment mandates, optionally adds a user approval signature, validates the chain, and demonstrates rejection for over-budget and disallowed-category carts.

**`/auto/configure` query parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `pollSeconds` | int | How often the agent polls Binance (1–3600) |
| `startingCash` | float | Simulated starting cash (1.00–1000.00) |
| `buyCooldownSeconds` | int | Minimum seconds between buys (0–86400) |
| `dropToBuyUsd` | float | USD drop required to trigger a buy (0.01–100000) |
| `riseToSellUsd` | float | USD rise from entry required to trigger a sell (0.01–100000) |

---

## Technical Indicators

All indicators are computed in pure Python from Binance kline data with no external libraries.

| Indicator | Parameters |
|-----------|-----------|
| EMA (fast) | Period 9 |
| EMA (mid) | Period 21 |
| EMA (slow) | Period 55 |
| RSI | Period 14 |
| MACD | Fast 12 / Slow 26 / Signal 9 |
| ATR | Period 14 |

The rule-based scoring system counts bullish and bearish signals from the above indicators. When `bullish_score - bearish_score >= BUY_THRESHOLD` the rule engine suggests BUY; when the gap is `<= -SELL_THRESHOLD` it suggests SELL. The OpenAI model receives this context alongside the raw indicator values and decides the final signal.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | _(required)_ | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4.1-nano` | OpenAI model to use |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1/responses` | OpenAI endpoint |
| `OPENAI_TIMEOUT` | `20` | Request timeout in seconds |
| `SIGNAL_REFRESH_SECONDS` | `300` | Seconds between OpenAI refreshes |
| `BINANCE_SYMBOL` | `BTCUSDT` | Trading pair to watch |
| `BINANCE_INTERVAL` | `15m` | Kline interval |
| `BINANCE_LOOKBACK` | `250` | Number of candles to fetch |
| `BINANCE_BASE_URL` | `https://api.binance.com` | Binance API base URL |
| `BINANCE_RETRY_COUNT` | `3` | Retries on Binance timeout |
| `BINANCE_RETRY_DELAY_SECONDS` | `2` | Delay between retries |
| `POLL_SECONDS` | `60` | Price check interval |
| `BUY_THRESHOLD` | `4` | Min bullish score gap to suggest BUY |
| `SELL_THRESHOLD` | `4` | Min bearish score gap to suggest SELL |
| `REQUEST_TIMEOUT` | `10` | HTTP request timeout in seconds |
| `AP2_SIM_SECRET` | _(internal fallback)_ | HMAC secret for local AP2-inspired simulation signing; set this for any non-throwaway demo |
| `AUTO_SIM_ENABLED` | `true` | Auto-start the simulation runner on API server start |
| `AUTO_SIM_POLL_SECONDS` | `5` | Poll interval for auto simulation |
| `AUTO_SIM_SIGNAL_REFRESH_SECONDS` | same as poll | Signal refresh interval for auto simulation |
| `AUTO_SIM_STARTING_CASH` | `500.0` | Starting cash for auto simulation |
| `AUTO_SIM_BUY_COOLDOWN_SECONDS` | `5` | Buy cooldown for auto simulation |
| `AUTO_SIM_DROP_TO_BUY_USD` | `1.0` | Buy trigger for auto simulation |
| `AUTO_SIM_RISE_TO_SELL_USD` | `1.0` | Sell trigger for auto simulation |
| `AGENT_API_HOST` | `127.0.0.1` | API server bind address |
| `AGENT_API_PORT` | `8765` | API server port |

If `api.binance.com` is unavailable in your region, use:

```env
BINANCE_BASE_URL=https://api.binance.us
```

---

## Example Console Output

```text
----------------------------------------------------------------------------------------------------
[2026-04-24 09:18:11] BTC: $77922.22 | NEW | Signal: HOLD | Action: WAIT | Confidence: 42%
SIM | Equity: $500.00 | Cash: $500.00 | BTC: 0.00000000 | Unrealized: +0.00 | Realized: +0.00 | Trades: 0

----------------------------------------------------------------------------------------------------
[2026-04-24 09:18:21] BTC: $77910.80 | DOWN -$11.42 | Signal: HOLD | Action: WAIT | Confidence: 42%
SIM | Equity: $500.00 | Cash: $0.00 | BTC: 0.00641744 | Unrealized: +0.00 | Realized: +0.00 | Trades: 1
AUTO BUY | Spent $500.00 | Bought 0.00641744 BTC at $77910.80 after a $11.42 drop | Cash: $500.00 -> $0.00

----------------------------------------------------------------------------------------------------
[2026-04-24 09:18:31] BTC: $77918.85 | UP +$8.05 | Signal: HOLD | Action: WAIT | Confidence: 42%
SIM | Equity: $500.05 | Cash: $500.05 | BTC: 0.00000000 | Unrealized: +0.00 | Realized: +0.05 | Trades: 2
AUTO SELL | Received $500.05 | P/L +0.05 (+0.01%) at $77918.85 after a $8.05 rise from entry | Cash: $0.00 -> $500.05 | Equity before sell: $500.05
```

---

## AP2-Inspired Simulation

This project simulates AP2-style payment mandate concepts for education and auditability. It does **not** implement real AP2 payment rails.

The `/ap2` API response includes a `protocol.implemented: false` flag and a `mode` of `AP2_INSPIRED_SIMULATION_ONLY` so clients can avoid mistaking this audit trail for AP2 compliance.

### Mandate types

| Mandate | Purpose |
|---------|---------|
| `Intent Mandate` | User authorization for simulated trading rules |
| `Cart Mandate` | Proposed simulated BUY or SELL |
| `Payment Mandate` | Final record for an executed simulated trade |

All mandates are:
- SHA-256 hashed for integrity
- HMAC-signed using `AP2_SIM_SECRET`
- Validated against the active simulated intent/cart before a simulated payment execution is logged
- Written to `ap2_logs/ap2_operations.json` and `ap2_logs/ap2_simulation_log.jsonl`

For real AP2 compliance, this project would still need AP2 mandate schemas and `vct` versioning, SD-JWT or another supported Verifiable Digital Credential format, Trusted Surface user signing, merchant-signed Checkout JWT binding, role-based verification, and Checkout/Payment Receipt JWTs.

### AP2 files

| File | Description |
|------|-------------|
| `ap2_sim.py` | Mandate creation, signing, validation, and audit logging |
| `ap2_mandates/active_intent_mandate.json` | Currently active user authorization |
| `ap2_logs/ap2_operations.json` | Structured operations audit log |
| `ap2_logs/ap2_simulation_log.jsonl` | Line-delimited audit trail |

### Supported audit event types

- `INTENT_MANDATE_CREATED`
- `CART_MANDATE_CREATED`
- `PAYMENT_MANDATE_CREATED`
- `SIMULATED_TRADE_EXECUTED`
- `SIMULATED_TRADE_BLOCKED`
- `MANDATE_VALIDATION_FAILED`

### AP2 self-test

```bash
python -c "import json, ap2_sim; print(json.dumps(ap2_sim.run_self_test(), indent=2))"
```

---

## Next.js Dashboard (optional)

The `web/` folder contains a Next.js 14 + React 18 development dashboard. You do **not** need it to run the agent — `dashboard.html` served by the Python API is sufficient.

To develop or extend the Next.js UI:

```bash
cd web
npm install
npm run dev
```

The dev server runs on `http://localhost:3000` and connects to the Python API at `http://127.0.0.1:8765`.

---

## Important Notes

- **No real trades are ever placed.** This is simulation only.
- **Not financial advice.**
- The live BTC price refreshes as fast as `POLL_SECONDS` allows, but the OpenAI signal is cached and refreshes every `SIGNAL_REFRESH_SECONDS` (default: 5 minutes) to reduce API costs.
- If OpenAI is unavailable or over quota, the agent continues running using the last cached or rule-based signal.
- If Binance times out, the agent retries automatically (`BINANCE_RETRY_COUNT` times) and then continues with the last known price instead of exiting.
