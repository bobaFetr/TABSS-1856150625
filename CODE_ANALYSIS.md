# Code analysis and functionality testing

## Fix verification

The four confirmed input-validation findings below have now been fixed. Shared validation rejects non-finite numbers, checkout requires actual JSON booleans and positive integer quantities, backtests validate candle structure/prices/order, and indicator periods must be positive integers. Non-finite environment settings fall back to defaults. Invalid checkout and NaN configuration requests return HTTP 400.

All 53 Python tests pass, including 12 new regression tests with multiple input cases. All 46 exploratory probes were rerun and their output refreshed. Frontend contract tests and lint pass. The historical review below describes the original behavior, before these fixes. The earlier intermittent HTTP connection reset was not reproduced during fix verification; its cause has not been established or claimed fixed.

Tested on September 14, 2026 using the project's Python virtual environment and installed frontend dependencies. Application source was not changed. Existing runtime-file and next-env.d.ts modifications were present before the review.

## Confirmed findings

1. **High: non-finite numbers bypass validation.** `api_server.py:219` checks lower/upper bounds with comparisons that both return false for NaN. `startingCash=NaN` is accepted. `ap2_sim.py:939` similarly accepts a NaN spending limit, and the comparison in `validate_payment_chain` fails to enforce the budget. A checkout with `maximumSpendingAmount: "NaN"` and a $1,000,000 book passes chain validation. Require finite numbers before range checks and serialization. This affects simulated mandates; no real payment occurs.
2. **Medium: checkout silently changes input meaning.** `api_server.py:102` uses `bool()` on JSON values: `"false"` becomes true for all three approval/presence flags. Quantity `1.9` becomes `1`, and boolean true becomes quantity `1` in the item normalizers. Validate boolean and integer types explicitly; reject unsupported values.
3. **Medium: historical inputs can crash or produce invalid results.** `backtest.py:31` accepts NaN/Infinity starting cash, producing NaN returns. Zero open price produces ZeroDivisionError; malformed rows produce IndexError. Validate finite positive prices/cash, row shape, OHLC consistency, and chronological ordering before evaluation.
4. **Low: indicator period validation is incomplete.** `indicators.py:6` raises ZeroDivisionError for EMA periods 0 and -1. Reject non-positive/non-integer periods consistently across indicators.

## Validation performed

- Existing Python suite: final full run passed all 41 tests. The initial run had 40 passes and one ConnectionResetError in the non-JSON content-type HTTP test; all 16 API tests also passed on immediate retry. The reset is intermittent and needs repeated targeted diagnosis before attributing its cause.
- Frontend: all four route-contract tests passed; Biome lint and Next.js production build, including TypeScript checking, passed.
- `input_analysis.py` adds 46 offline probes covering cash bounds, polling bounds, boolean inputs, candle counts, malformed candle rows, zero prices, indicator periods, fractional/null/boolean quantities, and NaN checkout budgets. Results are in `input_analysis_results.json`; NaN/Infinity tokens intentionally preserve observed Python output and are not strict JSON.
- Existing tests exercise trade fees/slippage, signal confirmation, fallback/retry behavior, atomic state persistence, mandate tampering/expiry/parent links, budget rejection, concurrent audit appends, API authentication, body limits, and POST-only mutations.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe input_analysis.py
cd web
npm.cmd test
npm.cmd run lint
npm.cmd run build
```

The default system Python lacks cryptography; the existing virtual environment has the dependency. npm.cmd is used because PowerShell blocks npm.ps1 under the current execution policy.

Coverage is offline and automated: live Binance/OpenAI connectivity, browser interaction, Docker startup, and prolonged simulation operation were not exercised. The additional probes use temporary AP2 storage and do not contact external services.
