"""Offline input probes; run with .venv/Scripts/python.exe input_analysis.py."""
import json
import os
import tempfile
from dataclasses import asdict
from unittest.mock import patch


def main():
    with tempfile.TemporaryDirectory() as directory:
        os.environ['AGENT_DATA_DIR'] = directory
        import api_server as api
        import backtest
        import ap2_sim
        import indicators

        results = []

        def probe(name, operation):
            try:
                results.append({'case': name, 'result': operation()})
            except Exception as exc:
                results.append({'case': name, 'error': type(exc).__name__, 'message': str(exc)})

        for value in ['0', '1', '500', '1000', '1001', '-1', 'abc', 'NaN', 'Infinity']:
            probe('startingCash=' + value, lambda v=value: api.query_float({'startingCash': [v]}, 'startingCash', 500, 1, 1000))
        for value in ['0', '1', '3600', '3601', '1.5', 'NaN']:
            probe('pollSeconds=' + value, lambda v=value: api.query_int({'pollSeconds': [v]}, 'pollSeconds', 5, 1, 3600))
        for value in ['true', 'false', '1', '0', 'yes', 'off', 'garbage']:
            probe('confirmation=' + value, lambda v=value: api.query_bool({'x': [v]}, 'x', False))
        rows = [[i, 100+i, 102+i, 99+i, 101+i, 1000] for i in range(100)]
        for cash in [0, 1, 1000, float('nan'), float('inf')]:
            probe('backtest cash=' + str(cash), lambda c=cash: asdict(backtest.run_backtest(rows, starting_cash=c)))
        for count in [0, 59, 60, 61, 100]:
            probe('backtest candles=' + str(count), lambda n=count: asdict(backtest.run_backtest(rows[:n])))
        invalid_rows = [row[:] for row in rows]
        invalid_rows[60][1] = 0
        probe('backtest zero execution open', lambda: asdict(backtest.run_backtest(invalid_rows)))
        probe('backtest malformed rows', lambda: backtest.run_backtest([[1]] * 61))
        for period in [0, -1, 1, 3, 4]:
            probe('EMA period=' + str(period), lambda p=period: indicators.ema([1, 2, 3], p))
        for quantity in [0, 1, 1.9, True, None]:
            probe('checkout quantity=' + str(quantity), lambda q=quantity: ap2_sim.normalize_cart_items([{'name': 'Book', 'category': 'books', 'quantity': q, 'unitPrice': 10}]))
        with patch.object(ap2_sim, 'run_checkout_scenario', side_effect=lambda **kw: kw):
            probe('checkout string false flags', lambda: api.run_checkout_payload({'humanApprovalRequired': 'false', 'approveCart': 'false', 'humanPresent': 'false'}))
        payload = {'maximumSpendingAmount': 'NaN', 'items': [{'name': 'Book', 'category': 'books', 'quantity': 1, 'unitPrice': 1000000}]}
        probe('checkout NaN budget with million dollar cart', lambda: api.run_checkout_payload(payload))
        print(json.dumps(results, indent=2, default=str))


if __name__ == '__main__':
    main()
