# BTC Signal Agent Hardening Plan

## Security and Secrets
- [ ] Rotate the OpenAI API key currently present in `.env`.
- [x] Remove `.env` from git tracking while keeping `.env.example`.
- [x] Add `.env`, `ap2_mandates/ap2_identities.json`, runtime logs, and Python cache files to `.gitignore`.
- [x] Document local secret setup using environment variables, not committed files.
- [x] Add a short note that GitHub secret scanning should be enabled for any hosted repository.

## Repo Hygiene
- [x] Remove tracked `__pycache__` files from version control.
- [x] Decide whether runtime state files belong in git; default to ignoring generated state/log files.
- [x] Keep committed sample files minimal and sanitized.
- [x] Add a short cleanup command section for local generated files.

## Simulation Safety
- [x] Keep all real trading disabled by default and preserve existing `realTradingEnabled: false` / `realMoneyMoved: false` semantics.
- [x] Add a visible README warning that Binance is used only for market data.
- [x] Add tests that fail if simulated mandates or payment records indicate real money movement.
- [x] Ensure dashboard/API copy consistently says simulation-only.

## API and Runtime Reliability
- [x] Require POST for mutations and optional bearer authentication on local deployments.
- [x] Refuse non-loopback binding unless `AGENT_API_TOKEN` is configured.
- [x] Remove wildcard CORS, bound request bodies, and sanitize internal errors.
- [x] Serialize signal cycles and atomically replace state snapshots.
- [x] Add tests for `/health`, `/auto/status`, `/auto/configure`, `/state`, and `/ap2`.
- [x] Add validation tests for invalid query params on `/auto/configure`.
- [x] Keep Binance failures non-fatal by preserving retry/fallback behavior.
- [x] Document supported Binance endpoints used by the app: ticker price and klines.

## OpenAI Signal Handling
- [x] Keep rule-based fallback when `OPENAI_API_KEY` is missing.
- [x] Add tests for OpenAI response parsing, invalid JSON, missing fields, and invalid signal values.
- [x] Document the configured OpenAI model and timeout environment variables.
- [x] Confirm structured JSON output remains the only accepted signal format.

## AP2-Inspired Demo Boundaries
- [x] Keep `/ap2` response exposing `protocol.implemented: false`.
- [x] Document that this is AP2-inspired only, not AP2-compliant.
- [x] Add tests for expired mandates, invalid signatures, mismatched parent IDs, and over-budget checkout rejection.
- [x] Prevent demo private keys from being committed.

## Frontend and Dashboard
- [x] Verify standalone `dashboard.html` works with the Python API only.
- [x] Verify Next.js dashboard builds with `npm run build`.
- [x] Add UI error states for Python API unavailable and last Binance/OpenAI error.
- [x] Keep Start/Pause/Apply behavior aligned between both dashboards.

## Test Checklist
- [x] Run `python3 -m py_compile btc_agent.py api_server.py ap2_sim.py`.
- [x] Run AP2 self-test if available.
- [x] Run API smoke tests against a local server.
- [x] Run `npm run build` in `web/`.
- [x] Verify no secrets or generated cache files remain tracked by git.
- [x] Add a reproducible Python dependency manifest.

## References
- OpenAI API docs: https://developers.openai.com/api/docs/quickstart
- GitHub secret scanning: https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning
- Binance Spot market data endpoints: https://developers.binance.com/legacy-docs/binance-spot-api-docs/rest-api/market-data-endpoints
- Google AP2 overview: https://developers.googleblog.com/en/agent-payments-protocol-ap2-an-open-protocol-for-agent-led-payments/
