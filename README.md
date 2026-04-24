# BTC Binance Signal Agent

This is a Python console agent that watches `BTCUSDT` on Binance, prints the live BTC price changes in the terminal, and asks OpenAI for a `BUY`, `SELL`, or `HOLD` signal based on the current market snapshot.

## What Changed

- the printed BTC price now comes from Binance's live ticker endpoint
- the trading signal now uses your `OPENAI_API_KEY`
- the same easy start method still works
- the AI signal is cached and refreshed every 5 minutes by default, so fast price updates do not trigger OpenAI on every loop

## Files

- `btc_agent.py` - console tracker and OpenAI signal logic
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
4. Leave the terminal window open while the tracker runs

If no key is configured yet, the launcher now asks for your OpenAI API key once and saves it to `.env`.

If you prefer PowerShell:

```powershell
.\start_web_app.ps1
```

## Example Console Output

```text
[2026-04-24 09:18:11] BTC: $77922.22 | NEW | Signal: HOLD | Action: WAIT | Confidence: 42%
[2026-04-24 09:18:21] BTC: $77935.80 | UP +$13.58 | Signal: BUY | Action: BUY | Confidence: 68%
[2026-04-24 09:18:31] BTC: $77901.15 | DOWN -$34.65 | Signal: SELL | Action: SELL | Confidence: 72%
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
