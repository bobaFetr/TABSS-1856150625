# BTC Binance Signal Agent

A Python-based trading signal agent that watches a Binance pair (`BTCUSDT` by default) in real time, computes technical indicators (RSI, EMA, MACD, ATR), and optionally queries OpenAI for a `BUY`, `SELL`, or `HOLD` recommendation. Includes a built-in web dashboard, a local JSON API, an auto-simulation mode, and an AP2-inspired mandate audit trail.

> **This is a simulation only. No real orders are placed and no real money moves. Binance is used only for public market data.**

---

## Project Structure

```
TABSS-1856150625/
├── btc_agent.py            # Core agent: market data, indicators, OpenAI signal, simulation engine
├── api_server.py           # Local HTTP API (port 8765) + dashboard server
├── ap2_sim.py              # AP2-inspired mandate creation, signing, and audit logging
├── dashboard.html          # Standalone web dashboard (served by api_server.py)
├── web/                    # Next.js dashboard (optional development UI)
├── agent_state.json        # Runtime signal/position snapshot
├── auto_sim_state.json     # Runtime auto-simulation snapshot
├── ap2_mandates/           # Runtime simulated mandate JSON
├── ap2_logs/               # Runtime AP2-inspired audit logs
├── .env                    # Your local secrets, ignored by git
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
- `cryptography` for the ECDSA mandate-signing simulation (installed from `requirements.txt`)
- An optional [OpenAI API key](https://platform.openai.com/account/api-keys); without one, the rule-based fallback is used
- Internet access to reach the configured Binance endpoint and, when enabled, the OpenAI API

---

## First-Time Setup

1. Install the Python dependency and create a `.env` file in the project root (copy from `.env.example`). Keep real API keys in local environment variables or `.env`; never commit them:

```bash
python -m pip install -r requirements.txt
```

On systems where Python 3 is exposed as `python3` rather than `python`, use `python3` in the commands throughout this README.

```env
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4.1-nano
BINANCE_SYMBOL=BTCUSDT
BINANCE_INTERVAL=15m
BINANCE_LOOKBACK=250
OPENAI_TIMEOUT=20
```

2. The console launcher (`start_web_app.ps1`, also invoked by `start_web_app.bat`) prompts for an OpenAI key and saves it when neither the environment nor `.env` provides one. The Python agent, API server, dashboards, and Docker setup can run without a key by using the rule-based fallback.

3. If this project is hosted on GitHub, enable secret scanning for the repository. If a real key was ever committed, rotate it in the provider dashboard before continuing.

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

**Start the standalone Python dashboard (no Node.js required):**

```cmd
START_DASHBOARD.cmd
```

Then open **http://127.0.0.1:8765** in your browser.

The dashboard is served directly by `api_server.py` from `dashboard.html` — no Node.js or `npm` is needed at runtime.

**Start the richer Next.js dashboard plus the Python API:**

```cmd
start_dashboard.bat
```

The Next.js dashboard opens at **http://127.0.0.1:3000** and proxies requests to the Python API at port `8765`. The launcher installs frontend dependencies when `web/node_modules` is missing.

**Use custom API and Next.js ports (PowerShell):**

```powershell
powershell -ExecutionPolicy Bypass -File .\start_dashboard.ps1 -ApiPort 8765 -WebPort 3000
```

### Dashboard simulation defaults

| Setting | Default | Range |
|---------|---------|-------|
| Starting cash | `$500.00` | `$1.00` – `$1000.00` |
| Loop interval | 5 seconds | 1 – 3600 seconds |
| Buy cooldown | 5 seconds | 0 – 86400 seconds |
| Buy trigger (drop) | `$25.00` | `$0.01` – `$100000.00` |
| Sell trigger (rise) | `$25.00` | `$0.01` – `$100000.00` |
| Simulated fee | 10 bps (0.10%) | 0 – 1000 bps |
| Simulated slippage | 2 bps (0.02%) | 0 – 1000 bps |

Press **Apply** to save new values. If the simulation is running, it restarts with a fresh simulated balance and the new settings. If it is stopped, the settings are saved and take effect when **Start** is pressed.

---

## Local JSON API

`api_server.py` starts a `ThreadingHTTPServer` on `http://127.0.0.1:8765`.

Binance endpoints used by this app:

- `GET /api/v3/ticker/price` for the latest public BTC price
- `GET /api/v3/klines` for public candlestick data

| Endpoint | Description |
|----------|-------------|
| `GET /` or `/dashboard` | Serves `dashboard.html` |
| `GET /health` | Returns `{"ok": true}` with API version |
| `POST /signal` | Runs one agent cycle and returns the signal result |
| `GET /state` | Returns the current `agent_state.json` contents |
| `POST /auto/start` | Starts the background auto-simulation runner |
| `POST /auto/stop` | Stops the auto-simulation runner |
| `GET /auto/status` | Returns current simulation state and last signal |
| `POST /auto/configure` | Saves query-param settings; restarts the runner only when it is already running |
| `GET /ap2` | Returns the active simulated mandate, audit log entries, and simulation-only protocol metadata |
| `POST /ap2/checkout/demo` | Runs the built-in simulated checkout chain |
| `POST /ap2/checkout/run` | Creates and validates a custom simulated checkout scenario from the supplied JSON inputs |

All state-changing routes are POST-only and require `Content-Type: application/json`. The API binds to loopback by default. Set `AGENT_API_TOKEN` to require `Authorization: Bearer <token>` on state-changing requests. A non-loopback `AGENT_API_HOST` is refused unless this token is configured. Cross-origin access is disabled unless one exact `AGENT_CORS_ORIGIN` is configured. The standalone dashboard asks for the token on the first protected action and keeps it only for the current browser tab; the Next.js proxy reads it server-side from the environment.

The `/signal` query accepts validated `symbol`, `interval`, `lookback`, `requestTimeout`, `buyThreshold`, and `sellThreshold` values. It also accepts `pollSeconds` for configuration compatibility, although polling has no practical effect on this one-cycle endpoint. Network destinations and state-file paths cannot be supplied through the API; configure `BINANCE_BASE_URL` and `STATE_FILE` in the trusted process environment instead.

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
| `feeRateBps` | float | Simulated fee in basis points (0–1000) |
| `slippageBps` | float | Simulated adverse execution slippage in basis points (0–1000) |
| `requireSignalConfirmation` | bool | Require BUY/SELL signal agreement in addition to the price trigger |

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

The scoring system counts bullish and bearish evidence from the indicators and volume. `BUY_THRESHOLD` and `SELL_THRESHOLD` control how the market snapshot describes that score gap as bullish, bearish, or mixed. The current no-key fallback emits `BUY` at a score gap of at least `4`, `SELL` at `-4` or lower, and `HOLD` otherwise. When an OpenAI key is configured, the model receives the snapshot, raw indicator values, scores, and reasons and returns the final structured signal.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | _(optional)_ | OpenAI API key; omit it to use rule-based signals |
| `OPENAI_MODEL` | `gpt-4.1-nano` | OpenAI model to use |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1/responses` | OpenAI endpoint |
| `OPENAI_TIMEOUT` | `20` | Request timeout in seconds |
| `SIGNAL_REFRESH_SECONDS` | `300` | Seconds between full candle/indicator and OpenAI refreshes in console mode |
| `BINANCE_SYMBOL` | `BTCUSDT` | Trading pair to watch |
| `BINANCE_INTERVAL` | `15m` | Kline interval |
| `BINANCE_LOOKBACK` | `250` | Number of candles to fetch |
| `BINANCE_BASE_URL` | `https://api.binance.com` | Binance API base URL |
| `BINANCE_RETRY_COUNT` | `3` | Total Binance attempts per cycle after retryable failures |
| `BINANCE_RETRY_DELAY_SECONDS` | `2` | Delay between retries |
| `POLL_SECONDS` | `60` | Price check interval |
| `BUY_THRESHOLD` | `4` | Bullish score-gap label used in the market snapshot |
| `SELL_THRESHOLD` | `4` | Bearish score-gap label used in the market snapshot |
| `REQUEST_TIMEOUT` | `10` | HTTP request timeout in seconds |
| `STATE_FILE` | `agent_state.json` | Signal/position state path; use an absolute path to place it outside the project directory |
| `AP2_SIM_SECRET` | _(internal fallback)_ | HMAC secret for local AP2-inspired simulation signing; set this for any non-throwaway demo |
| `AUTO_SIM_ENABLED` | `true` | Auto-start the simulation runner on API server start |
| `AUTO_SIM_POLL_SECONDS` | `5` | Poll interval for auto simulation |
| `AUTO_SIM_SIGNAL_REFRESH_SECONDS` | same as poll | Full candle/indicator and OpenAI refresh interval for auto simulation |
| `AUTO_SIM_STARTING_CASH` | `500.0` | Starting cash for auto simulation |
| `AUTO_SIM_BUY_COOLDOWN_SECONDS` | `5` | Buy cooldown for auto simulation |
| `AUTO_SIM_DROP_TO_BUY_USD` | `25.0` | Buy trigger for auto simulation |
| `AUTO_SIM_RISE_TO_SELL_USD` | `25.0` | Sell trigger for auto simulation |
| `AUTO_SIM_FEE_RATE_BPS` | `10.0` | Simulated execution fee in basis points |
| `AUTO_SIM_SLIPPAGE_BPS` | `2.0` | Simulated adverse slippage in basis points |
| `AUTO_SIM_REQUIRE_SIGNAL_CONFIRMATION` | `false` | Require signal agreement before a price-triggered trade |
| `AGENT_API_HOST` | `127.0.0.1` | API server bind address |
| `AGENT_API_PORT` | `8765` | API server port |
| `AGENT_API_TOKEN` | _(empty)_ | Bearer token required for mutations when configured; mandatory for non-loopback binding |
| `AGENT_CORS_ORIGIN` | _(empty)_ | Exact browser origin allowed for cross-origin API requests; wildcard origins are not supported |
| `AGENT_DATA_DIR` | project directory | Base directory for auto-simulation state, AP2 mandates, identities, and audit logs; Docker uses `/data` |
| `PY_AGENT_API_URL` | `http://127.0.0.1:8765` | Python backend URL used by the Next.js server-side proxy |

### Configuration loading

- `btc_agent.py` loads the project-root `.env` without overwriting variables already present in the process environment. This covers the agent settings and API settings that are read after startup.
- For local API runs, set `AGENT_DATA_DIR` in the process environment before starting Python to relocate all storage consistently. Because `ap2_sim` is imported before the project-root `.env` is loaded, an `AGENT_DATA_DIR` entry only in that file is too late for the AP2 paths (even though the API's auto-status path sees it).
- A direct `ap2_sim.py` CLI run does not load the project-root `.env`; provide `AGENT_DATA_DIR` or `AP2_SIM_SECRET` through the process environment when needed.
- Next.js reads `PY_AGENT_API_URL` and `AGENT_API_TOKEN` from its server environment. For manual `npm run dev`, set them in the shell or in `web/.env.local`. Docker Compose supplies them to the frontend container automatically.
- Docker Compose reads the project-root `.env` for `${...}` substitution and explicitly passes the supported values into its containers.

If `api.binance.com` is unavailable in your region, use:

```env
BINANCE_BASE_URL=https://api.binance.us
```

---

## Console Output

Live mode prints the current BTC price, price movement, signal, execution action, confidence, and indicator reasons. Auto-simulation mode additionally prints equity, cash, BTC balance, realized/unrealized P&L, trade count, fees, effective execution price, market price, and AP2-inspired mandate events. Exact values depend on live Binance data and the configured trigger, fee, and slippage settings.

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

The simulated trading mandates are:

- SHA-256 hashed for integrity
- HMAC-signed using `AP2_SIM_SECRET`
- Validated against the active simulated intent/cart before a simulated payment execution is logged
- Written to `ap2_logs/ap2_operations.json` and `ap2_logs/ap2_simulation_log.jsonl`

The separate shopping checkout demo uses generated ECDSA P-256 participant keys and stores its local identity registry in `ap2_mandates/ap2_identities.json`.

For real AP2 compliance, this project would still need AP2 mandate schemas and `vct` versioning, SD-JWT or another supported Verifiable Digital Credential format, Trusted Surface user signing, merchant-signed Checkout JWT binding, role-based verification, and Checkout/Payment Receipt JWTs.

### AP2 files

| File | Description |
|------|-------------|
| `ap2_sim.py` | Mandate creation, signing, validation, and audit logging |
| `ap2_mandates/active_intent_mandate.json` | Currently active user authorization |
| `ap2_mandates/ap2_identities.json` | Locally generated ECDSA identities for the shopping demo; ignored by git |
| `ap2_logs/ap2_operations.json` | Structured operations audit log |
| `ap2_logs/ap2_simulation_log.jsonl` | Line-delimited audit trail |

### Supported audit event types

Trading simulation:

- `INTENT_MANDATE_CREATED`
- `CART_MANDATE_CREATED`
- `PAYMENT_MANDATE_CREATED`
- `SIMULATED_TRADE_EXECUTED`
- `SIMULATED_TRADE_BLOCKED`
- `MANDATE_VALIDATION_FAILED`

Shopping checkout simulation:

- `SHOPPING_INTENT_MANDATE_CREATED`
- `SHOPPING_CART_MANDATE_CREATED`
- `SHOPPING_CART_APPROVED`
- `SHOPPING_PAYMENT_MANDATE_CREATED`

### AP2 self-test

```bash
python -c "import json, ap2_sim; print(json.dumps(ap2_sim.run_self_test(), indent=2))"
```

---

## Local Cleanup

The current repository tracks `agent_state.json`, `auto_sim_state.json`, the active intent mandate, and both AP2 audit logs as runtime snapshots. Running the app can modify them, so review `git status` before committing. Local secrets, caches, temporary output, frontend build/dependency folders, and `ap2_mandates/ap2_identities.json` are ignored. To remove runtime artifacts intentionally (tracked snapshots will then appear as deletions):

```bash
find . -type d -name __pycache__ -prune -exec rm -rf {} +
rm -f agent_state.json auto_sim_state.json tmp_out.txt tmp_err.txt
rm -rf ap2_logs ap2_mandates
```

---

## Next.js Dashboard (optional)

The `web/` folder currently uses Next.js 16, React 19, TypeScript, Lucide icons, and Biome. You do **not** need it to run the agent — `dashboard.html` served by the Python API is sufficient.

To develop or extend the Next.js UI:

```bash
cd web
npm ci
npm run dev
```

The dev server runs on `http://localhost:3000`. Start `python api_server.py` separately; the Next.js server-side route proxies to `PY_AGENT_API_URL`, which defaults to `http://127.0.0.1:8765`.

---

## Docker Desktop

The backend and Next.js frontend can run together with Docker Compose. From the project root:

```bash
docker compose up --build
```

Then open **http://localhost:3000**. The backend health endpoint is available at **http://localhost:8765/health**.

Docker Desktop will show a `btc-simulation-agent` application containing `backend` and `frontend`. You can stop and start both containers from that application. Runtime state is stored in the named `agent-data` volume and survives ordinary container recreation.

The Compose services bind-mount the local backend and frontend source directories. Therefore, starting the existing containers from Docker Desktop always runs the current files from this project folder instead of an older copy baked into an image. Frontend edits also hot-reload while the container is running. Restart the backend container from Docker Desktop after changing Python code.

If `requirements.txt`, `web/package.json`, `web/package-lock.json`, a Dockerfile, or `compose.yaml` changes, recreate the application once from the project root:

```bash
docker compose up --build --force-recreate -d
```

Normal Python, TypeScript, CSS, HTML, and documentation changes do not require an image rebuild.

To configure the containers, create a `.env` file beside `compose.yaml`. For example:

```env
AGENT_API_TOKEN=replace-with-a-long-random-value
AP2_SIM_SECRET=replace-with-another-long-random-value
OPENAI_API_KEY=
AUTO_SIM_STARTING_CASH=100
AUTO_SIM_POLL_SECONDS=2
AUTO_SIM_BUY_COOLDOWN_SECONDS=2
AUTO_SIM_DROP_TO_BUY_USD=0.01
AUTO_SIM_RISE_TO_SELL_USD=0.01
```

Leaving `OPENAI_API_KEY` empty uses the rule-based fallback. The Compose defaults also work without a `.env` file. To stop the application without deleting its saved data:

```bash
docker compose down
```

To intentionally delete the saved Docker simulation data as well:

```bash
docker compose down --volumes
```

---

## Important Notes

- **No real trades are ever placed.** This is simulation only.
- **Not financial advice.**
- The live BTC ticker is fetched every poll. In console mode, the full candle/indicator snapshot and OpenAI signal refresh at `SIGNAL_REFRESH_SECONDS` (default: 5 minutes); between refreshes, the cached snapshot is reused with the new live price. The API auto runner instead defaults `AUTO_SIM_SIGNAL_REFRESH_SECONDS` to its poll interval (5 seconds unless configured).
- If OpenAI is unavailable or over quota, the agent continues running using the last cached or rule-based signal.
- On a retryable Binance failure, each cycle makes up to `BINANCE_RETRY_COUNT` total attempts. After that, a running tracker reuses its last complete result when one exists; the first cycle reports an error because no stale result is available yet.
