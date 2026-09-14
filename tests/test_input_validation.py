import unittest
from unittest.mock import patch

import api_server
import ap2_sim
import backtest
import btc_agent
import indicators


def candles():
    return [[i, 100, 102, 99, 101, 1000] for i in range(61)]


class InputValidationTests(unittest.TestCase):
    def test_non_finite_api_and_backtest_numbers(self):
        for value in ['NaN', 'Infinity', '-Infinity']:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    api_server.query_float({'x': [value]}, 'x', 1, 0, 1000)
                for field in ['starting_cash', 'fee_rate_bps', 'slippage_bps']:
                    with self.assertRaises(ValueError):
                        backtest.run_backtest(candles(), **{field: float(value)})
                with patch.dict('os.environ', {'TEST_NUMBER': value}):
                    self.assertEqual(btc_agent.env_float('TEST_NUMBER', 5), 5)

    def test_checkout_rejects_invalid_flags_before_execution(self):
        for field in ['humanApprovalRequired', 'approveCart', 'humanPresent']:
            for value in ['false', 'true', 0, 1, None]:
                with self.subTest(field=field, value=value):
                    with patch.object(ap2_sim, 'run_checkout_scenario') as run:
                        with self.assertRaises(ValueError):
                            api_server.run_checkout_payload({field: value})
                        run.assert_not_called()

    def test_checkout_preserves_json_boolean_values(self):
        for value in [True, False]:
            with patch.object(ap2_sim, 'run_checkout_scenario') as run:
                api_server.run_checkout_payload(dict.fromkeys(
                    ['humanApprovalRequired', 'approveCart', 'humanPresent'], value))
                for field in ['human_approval_required', 'approve_cart', 'human_present']:
                    self.assertIs(run.call_args.kwargs[field], value)

    def test_checkout_rejects_invalid_quantities_and_prices(self):
        for field, values in [('quantity', [1.9, True, None, 0, -1, '2']),
                              ('unitPrice', ['NaN', 'Infinity', None, True, 0, -1, 0.001])]:
            for value in values:
                item = {'name': 'Book', 'category': 'books', 'quantity': 1, 'unitPrice': 10}
                item[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    ap2_sim.normalize_cart_items([item])

    def test_checkout_rejects_non_finite_budget_without_side_effects(self):
        for value in ['NaN', 'Infinity', None, True]:
            with patch.object(ap2_sim, 'run_checkout_scenario') as run:
                with self.assertRaises(ValueError):
                    api_server.run_checkout_payload({'maximumSpendingAmount': value})
                run.assert_not_called()

    def test_signed_non_finite_budget_fails_chain_validation(self):
        intent = {'payload': {'mandateId': 'i', 'userId': 'u', 'maximumSpendingAmount': float('nan')}}
        cart = {'payload': {'mandateId': 'c', 'parentIntentMandateId': 'i', 'userId': 'u', 'totalAmount': 1000000}}
        payment = {'payload': {'parentIntentMandateId': 'i', 'parentCartMandateId': 'c', 'userId': 'u', 'amount': 1000000}}
        with patch.object(ap2_sim, 'verify_ecdsa_signed_record', return_value=(True, 'OK')), \
             patch.object(ap2_sim, 'validate_cart_user_approval', return_value=(True, 'OK')):
            valid, messages = ap2_sim.validate_payment_chain(
                intent_record=intent, cart_record=cart, payment_record=payment)
        self.assertFalse(valid)
        self.assertIn('finite', messages[0])

    def test_backtest_rejects_malformed_candles(self):
        for field, value in [(0, -1), (0, 59), (1, 0), (2, 90), (3, 110),
                             (4, float('nan')), (5, -1), (5, float('inf'))]:
            rows = candles()
            rows[60][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                backtest.run_backtest(rows)
        with self.assertRaises(ValueError):
            backtest.run_backtest([[1]] * 61)

    def test_backtest_accepts_numeric_csv_fields(self):
        result = backtest.run_backtest([[str(v) for v in row] for row in candles()])
        self.assertEqual(result.candles, 1)

    def test_all_indicator_periods_require_positive_integers(self):
        values = list(range(1, 61))
        for period in [0, -1, 1.5, True, None]:
            operations = [lambda: indicators.ema(values, period),
                          lambda: indicators.rsi(values, period),
                          lambda: indicators.atr(values, values, values, period)]
            for field in ['fast_period', 'slow_period', 'signal_period']:
                operations.append(lambda f=field: indicators.macd(values, **{f: period}))
            for operation in operations:
                with self.subTest(period=period), self.assertRaises(ValueError):
                    operation()

    def test_indicator_valid_outputs(self):
        self.assertEqual(indicators.ema([1, 2, 3], 1), [1, 2, 3])
        self.assertEqual(indicators.ema([1, 2, 3], 3), [2, 2, 2])
