# BTC Signal Agent Hardening Plan

## Security and Secrets
- [ ] Rotate the OpenAI API key currently present in `.env`.
- [ ] Remove `.env` from git tracking while keeping `.env.example`.
- [ ] Add `.env`, `ap2_mandates/ap2_identities.json`, runtime logs, and Python cache files to `.gitignore`.
- [ ] Document local secret setup using environment variables, not committed files.
- [ ] Add a short note that GitHub secret scanning should be enabled for any hosted repository.

## Repo Hygiene
- [ ] Remove tracked `__pycache__` files from version control.
- [ ] Decide whether runtime state files belong in git; default to ignoring generated state/log files.
- [ ] Keep committed sample files minimal and sanitized.
- [ ] Add a short cleanup command section for local generated files.

## Simulation Safety
- [ ] Keep all real trading disabled by default and preserve existing `realTradingEnabled: false` / `realMoneyMoved: false` semantics.
- [ ] Add a visible README warning that Binance is used only for market data.
- [ ] Add tests that fail if simulated mandates or payment records indicate real money movement.
- [ ] Ensure dashboard/API copy consistently says simulation-only.

## API and Runtime Reliability
- [ ] Add tests for `/health`, `/auto/status`, `/auto/configure`, `/state`, and `/ap2`.
- [ ] Add validation tests for invalid query params on `/auto/configure`.
- [ ] Keep Binance failures non-fatal by preserving retry/fallback behavior.
- [ ] Document supported Binance endpoints used by the app: ticker price and klines.

## OpenAI Signal Handling
- [ ] Keep rule-based fallback when `OPENAI_API_KEY` is missing.
- [ ] Add tests for OpenAI response parsing, invalid JSON, missing fields, and invalid signal values.
- [ ] Document the configured OpenAI model and timeout environment variables.
- [ ] Confirm structured JSON output remains the only accepted signal format.

## AP2-Inspired Demo Boundaries
- [ ] Keep `/ap2` response exposing `protocol.implemented: false`.
- [ ] Document that this is AP2-inspired only, not AP2-compliant.
- [ ] Add tests for expired mandates, invalid signatures, mismatched parent IDs, and over-budget checkout rejection.
- [ ] Prevent demo private keys from being committed.

## Frontend and Dashboard
- [ ] Verify standalone `dashboard.html` works with the Python API only.
- [ ] Verify Next.js dashboard builds with `npm run build`.
- [ ] Add UI error states for Python API unavailable and last Binance/OpenAI error.
- [ ] Keep Start/Pause/Apply behavior aligned between both dashboards.

## Test Checklist
- [ ] Run `python3 -m py_compile btc_agent.py api_server.py ap2_sim.py`.
- [ ] Run AP2 self-test if available.
- [ ] Run API smoke tests against a local server.
- [ ] Run `npm run build` in `web/`.
- [ ] Verify no secrets or generated cache files appear in `git status --short`.

## References
- OpenAI API docs: https://developers.openai.com/api/docs/quickstart
- GitHub secret scanning: https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning
- Binance Spot market data endpoints: https://developers.binance.com/legacy-docs/binance-spot-api-docs/rest-api/market-data-endpoints
- Google AP2 overview: https://developers.googleblog.com/en/agent-payments-protocol-ap2-an-open-protocol-for-agent-led-payments/
