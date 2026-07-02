from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ap2_sim


class Ap2SimulationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        self.path_patches = [
            patch.object(ap2_sim, "MANDATES_DIR", base / "ap2_mandates"),
            patch.object(ap2_sim, "LOGS_DIR", base / "ap2_logs"),
            patch.object(ap2_sim, "ACTIVE_INTENT_MANDATE_PATH", base / "ap2_mandates" / "active_intent_mandate.json"),
            patch.object(ap2_sim, "AP2_SIMULATION_LOG_PATH", base / "ap2_logs" / "ap2_simulation_log.jsonl"),
            patch.object(ap2_sim, "AP2_OPERATIONS_LOG_PATH", base / "ap2_logs" / "ap2_operations.json"),
            patch.object(ap2_sim, "AP2_IDENTITIES_PATH", base / "ap2_mandates" / "ap2_identities.json"),
        ]
        for path_patch in self.path_patches:
            path_patch.start()
        ap2_sim.ensure_storage()

    def tearDown(self) -> None:
        for path_patch in reversed(self.path_patches):
            path_patch.stop()
        self.temp_dir.cleanup()

    def test_intent_mandate_rejects_real_money_flags(self) -> None:
        intent = ap2_sim.create_intent_mandate(
            symbol="BTCUSDT",
            starting_cash_usd=500.0,
            buy_cooldown_seconds=10,
            buy_threshold_usd=25.0,
            sell_threshold_usd=40.0,
        )

        self.assertFalse(intent["payload"]["realTradingEnabled"])
        self.assertFalse(intent["payload"]["realMoneyMoved"])

        unsafe = copy.deepcopy(intent)
        unsafe["payload"]["realMoneyMoved"] = True
        unsafe = ap2_sim.create_signed_record(unsafe["payload"])
        valid, reason = ap2_sim.validate_intent_mandate(
            unsafe,
            expected_symbol="BTCUSDT",
            expected_action="BUY",
        )

        self.assertFalse(valid)
        self.assertIn("real money", reason)

    def test_expired_intent_mandate_is_rejected(self) -> None:
        intent = ap2_sim.create_intent_mandate(
            symbol="BTCUSDT",
            starting_cash_usd=500.0,
            buy_cooldown_seconds=10,
            buy_threshold_usd=25.0,
            sell_threshold_usd=40.0,
        )
        expired_payload = copy.deepcopy(intent["payload"])
        expired_payload["expiresAt"] = "2000-01-01T00:00:00+00:00"
        expired = ap2_sim.create_signed_record(expired_payload)

        valid, reason = ap2_sim.validate_intent_mandate(
            expired,
            expected_symbol="BTCUSDT",
            expected_action="BUY",
        )

        self.assertFalse(valid)
        self.assertIn("expired", reason)

    def test_invalid_hmac_signature_is_rejected(self) -> None:
        record = ap2_sim.create_signed_record({"mode": "SIMULATION"})
        record["signature"] = "bad-signature"

        valid, reason = ap2_sim.verify_signed_record(record)

        self.assertFalse(valid)
        self.assertIn("Signature", reason)

    def test_payment_mandate_parent_id_mismatch_is_rejected(self) -> None:
        intent = ap2_sim.create_intent_mandate(
            symbol="BTCUSDT",
            starting_cash_usd=500.0,
            buy_cooldown_seconds=10,
            buy_threshold_usd=25.0,
            sell_threshold_usd=40.0,
        )
        cart = ap2_sim.create_cart_mandate(
            intent_record=intent,
            action="BUY",
            symbol="BTCUSDT",
            price=65000.0,
            quantity=0.00769231,
            notional_usd=500.0,
            ai_signal="HOLD",
            ai_confidence=50,
            rule_trigger={
                "previousPrice": 65030.0,
                "currentPrice": 65000.0,
                "priceChangeUsd": -30.0,
                "buyThresholdUsd": 25.0,
            },
            reason="Test cart.",
        )
        payment_payload = {
            "mandateType": "PaymentMandate",
            "mandateId": "payment_test",
            "parentIntentMandateId": intent["payload"]["mandateId"],
            "parentCartMandateId": "wrong-cart",
            "agentId": ap2_sim.AGENT_ID,
            "symbol": "BTCUSDT",
            "mode": "SIMULATION",
            "status": "SIMULATED_EXECUTED",
            "executedAction": "BUY",
            "executionPrice": 65000.0,
            "quantity": 0.00769231,
            "notionalUsd": 500.0,
            "realMoneyMoved": False,
        }
        payment = ap2_sim.create_signed_record(payment_payload)

        valid, reason = ap2_sim.validate_payment_mandate(
            payment_record=payment,
            intent_record=intent,
            cart_record=cart,
            expected_symbol="BTCUSDT",
            expected_action="BUY",
        )

        self.assertFalse(valid)
        self.assertIn("parent Cart", reason)

    def test_checkout_rejects_over_budget_payment(self) -> None:
        result = ap2_sim.run_checkout_scenario(
            user_id="budget_user",
            merchant_id="budget_merchant",
            agent_id="budget_agent",
            maximum_spending_amount=50.0,
            currency="USD",
            allowed_categories=["software"],
            items=[{"name": "Course", "category": "software", "quantity": 1, "unitPrice": 75.0}],
            human_approval_required=True,
            approve_cart=True,
            human_present=True,
            payment_method="simulated_card",
        )

        self.assertFalse(result["valid"])
        self.assertTrue(any("spending limit" in message for message in result["messages"]))
        self.assertFalse(result["payment"]["payload"]["realMoneyMoved"])


if __name__ == "__main__":
    unittest.main()
