# BTC Binance Signal Agent

This is a Python console agent that watches `BTCUSDT` on Binance, prints the live BTC price changes in the terminal, and asks OpenAI for a `BUY`, `SELL`, or `HOLD` signal based on the current market snapshot.

## What Changed

- the printed BTC price now comes from Binance's live ticker endpoint
- the trading signal now uses your `OPENAI_API_KEY`
- the same easy start method still works
- the AI signal is cached and refreshed every 5 minutes by default, so fast price updates do not trigger OpenAI on every loop

## Files

- `btc_agent.py` - console tracker and OpenAI signal logic
- `api_server.py` - local JSON API used by the Next.js dashboard
- `web/` - Next.js dashboard for the local agent
- `start_web_app.ps1` - PowerShell launcher
- `start_web_app.bat` - double-click starter
- `agent_state.json` - remembers whether the agent is currently `FLAT` or `LONG`

## First-Time Setup

Best option for double-click startup:

1. Create a file named `.env` in this folder
2. Copy the contents of `.env.example`
3. Replace the key with your real key

Example `.env`:

```text
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4.1-nano
```

You can also set the key only for your current PowerShell session:

```powershell
$env:OPENAI_API_KEY="your_api_key_here"
```

Optional model override:

```powershell
$env:OPENAI_MODEL="gpt-4.1-nano"
```

The default model is `gpt-4.1-nano`.

## Easiest Start Method

1. Put your key in `.env` or set `OPENAI_API_KEY`
2. Double-click `start_web_app.bat`
3. Choose the update speed:
   - `1 second`
   - `10 seconds`
   - `1 minute`
   - `5` for `Simulate auto buy and sell`
4. Leave the terminal window open while the tracker runs

If you choose `5`, the app will ask:

- how much starting money to use, up to `$1000.00`
- how often it is allowed to buy again
- how big a BTC price drop should trigger a buy
- how big a rise from the buy price should trigger a sell

The simulation uses the starting money you enter, up to `$1000.00`, and then simulates trades automatically by buying on drops and selling on rises.

If no key is configured yet, the launcher now asks for your OpenAI API key once and saves it to `.env`.

If you prefer PowerShell:

```powershell
.\start_web_app.ps1
```

## Next.js Dashboard

Start the dashboard with one command:

```cmd
START_DASHBOARD.cmd
```

Open `http://127.0.0.1:8765`. Press `Ctrl+C` in the terminal to stop it.

This command does not use `npm`, PowerShell execution policy, or a separate Next.js dev server. The Python API serves the dashboard and the live agent from the same local address.

The Next.js app in `web/` is still available for development, but you do not need it to run the dashboard.

Optional custom ports:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_dashboard.ps1 -ApiPort 8765 -WebPort 3000
```

The web dashboard runs the simulation automatically. By default it checks BTC every 5 seconds, starts with `$500.00` simulated cash, buys after a `$1.00` drop from the previous observed price, and sells after a `$1.00` rise from the simulated entry price. This is still simulation only: no real Binance orders are placed and no real money moves.

You can change these rules from the dashboard:

- `Money` - simulated cash to start with, from `$1.00` to `$1000.00`
- `Loop sec` - how often the agent checks BTC
- `Buy again sec` - cooldown before another simulated buy is allowed
- `Buy drop $` - how far BTC must drop from the previous observed price before buying
- `Sell rise $` - how far BTC must rise from the simulated entry price before selling

Press `Apply` to restart the simulation with the new values.

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

## Optional Direct Commands

Run once:

```powershell
C:\Users\Lenovo\AppData\Local\Python\pythoncore-3.14-64\python.exe .\btc_agent.py --once
```

Run live with a fixed refresh speed:

```powershell
C:\Users\Lenovo\AppData\Local\Python\pythoncore-3.14-64\python.exe .\btc_agent.py --poll-seconds 10
```

## Optional Settings

```powershell
$env:BINANCE_SYMBOL="BTCUSDT"
$env:BINANCE_INTERVAL="15m"
$env:BINANCE_LOOKBACK="250"
$env:POLL_SECONDS="60"
$env:BINANCE_BASE_URL="https://api.binance.com"
$env:BUY_THRESHOLD="4"
$env:SELL_THRESHOLD="4"
$env:OPENAI_TIMEOUT="20"
$env:SIGNAL_REFRESH_SECONDS="300"
$env:BINANCE_RETRY_COUNT="3"
$env:BINANCE_RETRY_DELAY_SECONDS="2"
```

If `api.binance.com` is unavailable for your region, try:

```powershell
$env:BINANCE_BASE_URL="https://api.binance.us"
```

## Important Notes

- this does not place trades automatically
- this is not financial advice
- the BTC price can refresh every second, but the OpenAI signal refreshes every 5 minutes by default
- if OpenAI is unavailable or out of quota, the tracker now keeps running and falls back to a cached or rule-based signal
- if Binance times out, the tracker now retries automatically and then keeps running with the last known price instead of exiting
- console output is printed in separated blocks so each update is easier to read

## AP2-Inspired Simulation

This project does not implement real AP2 payment rails. It simulates AP2-style mandate concepts for education, auditability, and a graduation project.

- `Intent Mandate` = the user's authorization for simulated BTCUSDT trading rules
- `Cart Mandate` = a proposed simulated BUY or SELL
- `Payment Mandate` = the final record for an executed simulated trade
- all mandates are hashed with SHA-256 and signed with simulated HMAC signatures
- no real money is moved
- no real Binance orders are placed
- the simulation stays in `SIMULATION` mode only

AP2 simulation files:

- [ap2_sim.py](</c:/Users/Lenovo/Desktop/python ai agent buy sell/ap2_sim.py:1>) - mandate creation, signing, validation, and audit logging
- [ap2_mandates/active_intent_mandate.json](</c:/Users/Lenovo/Desktop/python ai agent buy sell/ap2_mandates/active_intent_mandate.json:1>) - active user simulation authorization
- [ap2_logs/ap2_simulation_log.jsonl](</c:/Users/Lenovo/Desktop/python ai agent buy sell/ap2_logs/ap2_simulation_log.jsonl:1>) - audit trail of mandate and simulated trade events

Environment variable for simulated signing:

```powershell
$env:AP2_SIM_SECRET="your_local_simulation_secret"
```

If `AP2_SIM_SECRET` is missing, the app uses a safe local development fallback secret internally.

Supported AP2 simulation audit events:

- `INTENT_MANDATE_CREATED`
- `CART_MANDATE_CREATED`
- `PAYMENT_MANDATE_CREATED`
- `SIMULATED_TRADE_EXECUTED`
- `SIMULATED_TRADE_BLOCKED`
- `MANDATE_VALIDATION_FAILED`

Simple self-test:

```powershell
C:\Users\Lenovo\AppData\Local\Python\pythoncore-3.14-64\python.exe -c "import json, ap2_sim; print(json.dumps(ap2_sim.run_self_test(), indent=2))"
```
