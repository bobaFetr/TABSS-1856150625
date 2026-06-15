from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import uuid
from base64 import b64decode, b64encode
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


BASE_DIR = Path(__file__).resolve().parent
MANDATES_DIR = BASE_DIR / "ap2_mandates"
LOGS_DIR = BASE_DIR / "ap2_logs"
ACTIVE_INTENT_MANDATE_PATH = MANDATES_DIR / "active_intent_mandate.json"
AP2_SIMULATION_LOG_PATH = LOGS_DIR / "ap2_simulation_log.jsonl"
AP2_OPERATIONS_LOG_PATH = LOGS_DIR / "ap2_operations.json"
AP2_IDENTITIES_PATH = MANDATES_DIR / "ap2_identities.json"
AGENT_ID = "btc_binance_signal_agent"
DEFAULT_SIM_SECRET = "local-dev-ap2-simulation-secret"
SIMULATION_ONLY_NOTICE = (
    "AP2-inspired local simulation only. This is not a compliant AP2 implementation "
    "and does not move real money or integrate with payment rails."
)
PROTOCOL_ALIGNMENT = {
    "implemented": False,
    "mode": "AP2_INSPIRED_SIMULATION_ONLY",
    "notice": SIMULATION_ONLY_NOTICE,
    "localGuarantees": [
        "Local JSON payload integrity hashes",
        "Local HMAC signatures using AP2_SIM_SECRET",
        "Deterministic simulation rule checks before simulated trades",
        "Append-only local audit events",
    ],
    "missingForRealAp2": [
        "AP2 Checkout Mandate schemas and vct version claims",
        "SD-JWT or other Verifiable Digital Credential format",
        "Trusted Surface user signing flow",
        "Merchant-signed Checkout JWT binding",
        "Credential Provider, Network, and Merchant Payment Processor verification",
        "Checkout Receipt and Payment Receipt JWTs",
        "Real payment instrument or payment rail integration",
    ],
}
_STORAGE_LOCK = threading.Lock()


def ap2_warning(message: str) -> None:
    print(f"AP2 SIM | Warning | {message}")


def ensure_storage() -> None:
    try:
        MANDATES_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        if not ACTIVE_INTENT_MANDATE_PATH.exists():
            ACTIVE_INTENT_MANDATE_PATH.write_text("{}\n", encoding="utf-8")
        if not AP2_SIMULATION_LOG_PATH.exists():
            AP2_SIMULATION_LOG_PATH.touch()
        if not AP2_OPERATIONS_LOG_PATH.exists() or not AP2_OPERATIONS_LOG_PATH.read_text(encoding="utf-8").strip():
            AP2_OPERATIONS_LOG_PATH.write_text('{"operations": []}\n', encoding="utf-8")
        if not AP2_IDENTITIES_PATH.exists() or not AP2_IDENTITIES_PATH.read_text(encoding="utf-8").strip():
            AP2_IDENTITIES_PATH.write_text('{"participants": {}}\n', encoding="utf-8")
    except OSError as exc:
        ap2_warning(f"Could not initialize AP2 storage: {exc}")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat(timespec="seconds")


def iso_after(*, seconds: int = 0, hours: int = 0) -> str:
    return (utc_now() + timedelta(seconds=seconds, hours=hours)).isoformat(timespec="seconds")


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def get_sim_secret() -> str:
    return os.getenv("AP2_SIM_SECRET", DEFAULT_SIM_SECRET)


def using_default_sim_secret() -> bool:
    return get_sim_secret() == DEFAULT_SIM_SECRET


def compute_payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def sign_payload_hash(payload_hash: str) -> str:
    return hmac.new(
        get_sim_secret().encode("utf-8"),
        payload_hash.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_signed_record(payload: dict[str, Any]) -> dict[str, Any]:
    payload_hash = compute_payload_hash(payload)
    return {
        "payload": payload,
        "payloadHash": payload_hash,
        "signature": sign_payload_hash(payload_hash),
    }


def verify_signed_record(record: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(record, dict):
        return False, "Signed record is not a JSON object."

    payload = record.get("payload")
    payload_hash = record.get("payloadHash")
    signature = record.get("signature")

    if not isinstance(payload, dict):
        return False, "Signed record payload is missing or invalid."
    if not isinstance(payload_hash, str) or not payload_hash:
        return False, "Signed record payload hash is missing."
    if not isinstance(signature, str) or not signature:
        return False, "Signed record signature is missing."

    expected_hash = compute_payload_hash(payload)
    if expected_hash != payload_hash:
        return False, "Payload hash verification failed."

    expected_signature = sign_payload_hash(payload_hash)
    if not hmac.compare_digest(expected_signature, signature):
        return False, "Signature verification failed."

    return True, "OK"


def parse_iso_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_expired(value: str) -> bool:
    timestamp = parse_iso_timestamp(value)
    if timestamp is None:
        return True
    return timestamp.astimezone(timezone.utc) < utc_now()


def build_mandate_id(prefix: str) -> str:
    return f"{prefix}_{utc_now().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"


def save_json(path: Path, payload: dict[str, Any]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw_payload = json.dumps(payload, indent=2, ensure_ascii=True) + "\n"
        tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with _STORAGE_LOCK:
            tmp_path.write_text(raw_payload, encoding="utf-8")
            os.replace(tmp_path, path)
        return True
    except OSError as exc:
        ap2_warning(f"Could not save {path.name}: {exc}")
        return False


def append_jsonl(path: Path, line_payload: dict[str, Any]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _STORAGE_LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line_payload, ensure_ascii=True) + "\n")
        return True
    except OSError as exc:
        ap2_warning(f"Could not append {path.name}: {exc}")
        return False


def append_operation_json(path: Path, operation: dict[str, Any]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _STORAGE_LOCK:
            current_payload: dict[str, Any] = {"operations": []}
            if path.exists():
                raw_data = path.read_text(encoding="utf-8").strip()
                if raw_data:
                    current_data = json.loads(raw_data)
                    if isinstance(current_data, dict) and isinstance(current_data.get("operations"), list):
                        current_payload = current_data
                    elif isinstance(current_data, list):
                        current_payload = {"operations": current_data}

            operations = current_payload["operations"]
            operations.append(operation)
            current_payload["operationCount"] = len(operations)
            current_payload["updatedAt"] = utc_now_iso()
            raw_payload = json.dumps(current_payload, indent=2, ensure_ascii=True) + "\n"
            tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            tmp_path.write_text(raw_payload, encoding="utf-8")
            os.replace(tmp_path, path)
        return True
    except (OSError, json.JSONDecodeError) as exc:
        ap2_warning(f"Could not update {path.name}: {exc}")
        return False


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    return data if isinstance(data, dict) else None


def append_audit_event(
    *,
    event_type: str,
    final_action: str,
    status: str,
    human_readable_reason: str,
    signed_record: dict[str, Any],
    intent_mandate_id: str | None = None,
    cart_mandate_id: str | None = None,
    payment_mandate_id: str | None = None,
) -> None:
    payload = signed_record.get("payload", {})
    entry = {
        "eventType": event_type,
        "createdAt": utc_now_iso(),
        "intentMandateId": intent_mandate_id,
        "cartMandateId": cart_mandate_id,
        "paymentMandateId": payment_mandate_id,
        "finalAction": final_action,
        "status": status,
        "humanReadableReason": human_readable_reason,
        "payload": payload,
        "payloadHash": signed_record.get("payloadHash", ""),
        "signature": signed_record.get("signature", ""),
    }
    append_jsonl(AP2_SIMULATION_LOG_PATH, entry)
    append_operation_json(AP2_OPERATIONS_LOG_PATH, entry)


def create_audit_record(payload: dict[str, Any]) -> dict[str, Any]:
    return create_signed_record(payload)


def create_intent_mandate(
    *,
    symbol: str,
    starting_cash_usd: float,
    buy_cooldown_seconds: int,
    buy_threshold_usd: float,
    sell_threshold_usd: float,
) -> dict[str, Any]:
    payload = {
        "mandateType": "IntentMandate",
        "mandateId": build_mandate_id("intent"),
        "agentId": AGENT_ID,
        "symbol": symbol,
        "mode": "SIMULATION",
        "allowedActions": ["BUY", "SELL"],
        "startingCashUsd": round(starting_cash_usd, 2),
        "buyCooldownSeconds": int(buy_cooldown_seconds),
        "buyRule": {
            "type": "drop_from_previous_observed_price",
            "thresholdUsd": round(buy_threshold_usd, 2),
        },
        "sellRule": {
            "type": "rise_from_entry_price",
            "thresholdUsd": round(sell_threshold_usd, 2),
        },
        "realTradingEnabled": False,
        "realMoneyMoved": False,
        "allowWithdrawals": False,
        "allowLeverage": False,
        "createdAt": utc_now_iso(),
        "expiresAt": iso_after(hours=24),
        "userConfirmation": "User authorized simulated BTCUSDT trading only.",
    }
    signed_record = create_signed_record(payload)
    save_json(ACTIVE_INTENT_MANDATE_PATH, signed_record)
    append_audit_event(
        event_type="INTENT_MANDATE_CREATED",
        final_action="HOLD",
        status="ACTIVE",
        human_readable_reason="User authorized AP2-inspired simulated BTCUSDT trading rules.",
        signed_record=signed_record,
        intent_mandate_id=payload["mandateId"],
    )
    return signed_record


def load_active_intent_mandate() -> tuple[dict[str, Any] | None, str]:
    ensure_storage()
    record = load_json(ACTIVE_INTENT_MANDATE_PATH)
    if not record:
        return None, "Active Intent Mandate file is missing or invalid."
    return record, "OK"


def validate_intent_mandate(
    record: dict[str, Any],
    *,
    expected_symbol: str,
    expected_action: str,
) -> tuple[bool, str]:
    valid, reason = verify_signed_record(record)
    if not valid:
        return False, reason

    payload = record["payload"]
    if payload.get("mandateType") != "IntentMandate":
        return False, "Active mandate is not an Intent Mandate."
    if payload.get("mode") != "SIMULATION":
        return False, "Intent Mandate is not in simulation mode."
    if payload.get("realTradingEnabled") is not False:
        return False, "Intent Mandate must keep real trading disabled."
    if payload.get("realMoneyMoved") is not False:
        return False, "Intent Mandate must keep real money movement disabled."
    if payload.get("symbol") != expected_symbol:
        return False, "Intent Mandate symbol does not match the trade symbol."
    if expected_action not in payload.get("allowedActions", []):
        return False, "Intent Mandate does not allow this action."
    if is_expired(str(payload.get("expiresAt", ""))):
        return False, "Intent Mandate is expired."

    return True, "OK"


def create_cart_mandate(
    *,
    intent_record: dict[str, Any],
    action: str,
    symbol: str,
    price: float,
    quantity: float,
    notional_usd: float,
    ai_signal: str,
    ai_confidence: int,
    rule_trigger: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    intent_payload = intent_record["payload"]
    payload = {
        "mandateType": "CartMandate",
        "mandateId": build_mandate_id("cart"),
        "parentIntentMandateId": intent_payload["mandateId"],
        "agentId": AGENT_ID,
        "symbol": symbol,
        "mode": "SIMULATION",
        "proposedAction": action,
        "price": round(price, 2),
        "quantity": round(quantity, 8),
        "notionalUsd": round(notional_usd, 2),
        "aiSignal": ai_signal,
        "aiConfidence": int(ai_confidence),
        "ruleTrigger": rule_trigger,
        "reason": reason,
        "createdAt": utc_now_iso(),
        "expiresAt": iso_after(seconds=60),
    }
    signed_record = create_signed_record(payload)
    append_audit_event(
        event_type="CART_MANDATE_CREATED",
        final_action=action,
        status="PROPOSED",
        human_readable_reason=reason,
        signed_record=signed_record,
        intent_mandate_id=intent_payload["mandateId"],
        cart_mandate_id=payload["mandateId"],
    )
    return signed_record


def values_match(left: float, right: float, *, precision: int) -> bool:
    return round(float(left), precision) == round(float(right), precision)


def validate_payment_mandate(
    *,
    payment_record: dict[str, Any],
    intent_record: dict[str, Any],
    cart_record: dict[str, Any],
    expected_symbol: str,
    expected_action: str,
) -> tuple[bool, str]:
    valid, reason = verify_signed_record(payment_record)
    if not valid:
        return False, reason

    valid, reason = verify_signed_record(intent_record)
    if not valid:
        return False, f"Parent Intent Mandate is invalid: {reason}"

    valid, reason = verify_signed_record(cart_record)
    if not valid:
        return False, f"Parent Cart Mandate is invalid: {reason}"

    payload = payment_record["payload"]
    intent_payload = intent_record["payload"]
    cart_payload = cart_record["payload"]
    action = str(payload.get("executedAction", "")).upper()

    if payload.get("mandateType") != "PaymentMandate":
        return False, "Proposed payment record is not a Payment Mandate."
    if payload.get("mode") != "SIMULATION":
        return False, "Payment Mandate is not in simulation mode."
    if payload.get("status") != "SIMULATED_EXECUTED":
        return False, "Payment Mandate status is not SIMULATED_EXECUTED."
    if payload.get("realMoneyMoved") is not False:
        return False, "Payment Mandate must keep real money movement disabled."
    if payload.get("symbol") != expected_symbol:
        return False, "Payment Mandate symbol does not match."
    if action != expected_action:
        return False, "Payment Mandate action does not match the simulated execution."
    if payload.get("parentIntentMandateId") != intent_payload.get("mandateId"):
        return False, "Payment Mandate does not reference the parent Intent Mandate."
    if payload.get("parentCartMandateId") != cart_payload.get("mandateId"):
        return False, "Payment Mandate does not reference the parent Cart Mandate."
    if cart_payload.get("parentIntentMandateId") != intent_payload.get("mandateId"):
        return False, "Parent Cart Mandate does not reference the parent Intent Mandate."
    if cart_payload.get("symbol") != expected_symbol:
        return False, "Parent Cart Mandate symbol does not match."
    if str(cart_payload.get("proposedAction", "")).upper() != action:
        return False, "Parent Cart Mandate action does not match the payment action."

    try:
        execution_price = float(payload.get("executionPrice", 0.0))
        payment_quantity = float(payload.get("quantity", 0.0))
        payment_notional = float(payload.get("notionalUsd", 0.0))
        cart_price = float(cart_payload.get("price", 0.0))
        cart_quantity = float(cart_payload.get("quantity", 0.0))
        cart_notional = float(cart_payload.get("notionalUsd", 0.0))
    except (TypeError, ValueError):
        return False, "Payment Mandate or Cart Mandate numeric values are invalid."

    if execution_price <= 0 or payment_quantity <= 0 or payment_notional <= 0:
        return False, "Payment Mandate price, quantity, and notional must be positive."
    if not values_match(execution_price, cart_price, precision=2):
        return False, "Payment Mandate execution price does not match the Cart Mandate."
    if not values_match(payment_quantity, cart_quantity, precision=8):
        return False, "Payment Mandate quantity does not match the Cart Mandate."
    if not values_match(payment_notional, cart_notional, precision=2):
        return False, "Payment Mandate notional does not match the Cart Mandate."

    return True, "OK"


def create_payment_mandate(
    *,
    intent_record: dict[str, Any],
    cart_record: dict[str, Any],
    action: str,
    symbol: str,
    execution_price: float,
    quantity: float,
    notional_usd: float,
    cash_before: float,
    cash_after: float,
    btc_before: float,
    btc_after: float,
    reason: str,
) -> dict[str, Any]:
    intent_payload = intent_record["payload"]
    cart_payload = cart_record["payload"]
    payload = {
        "mandateType": "PaymentMandate",
        "mandateId": build_mandate_id("payment"),
        "parentIntentMandateId": intent_payload["mandateId"],
        "parentCartMandateId": cart_payload["mandateId"],
        "agentId": AGENT_ID,
        "symbol": symbol,
        "mode": "SIMULATION",
        "status": "SIMULATED_EXECUTED",
        "executedAction": action,
        "executionPrice": round(execution_price, 2),
        "quantity": round(quantity, 8),
        "notionalUsd": round(notional_usd, 2),
        "cashBefore": round(cash_before, 2),
        "cashAfter": round(cash_after, 2),
        "btcBefore": round(btc_before, 8),
        "btcAfter": round(btc_after, 8),
        "realMoneyMoved": False,
        "reason": reason,
        "createdAt": utc_now_iso(),
    }
    signed_record = create_signed_record(payload)
    valid, validation_reason = validate_payment_mandate(
        payment_record=signed_record,
        intent_record=intent_record,
        cart_record=cart_record,
        expected_symbol=symbol,
        expected_action=action,
    )
    if not valid:
        raise ValueError(validation_reason)

    append_audit_event(
        event_type="PAYMENT_MANDATE_CREATED",
        final_action=action,
        status="SIMULATED_EXECUTED",
        human_readable_reason=reason,
        signed_record=signed_record,
        intent_mandate_id=intent_payload["mandateId"],
        cart_mandate_id=cart_payload["mandateId"],
        payment_mandate_id=payload["mandateId"],
    )
    append_audit_event(
        event_type="SIMULATED_TRADE_EXECUTED",
        final_action=action,
        status="SIMULATED_EXECUTED",
        human_readable_reason=reason,
        signed_record=signed_record,
        intent_mandate_id=intent_payload["mandateId"],
        cart_mandate_id=cart_payload["mandateId"],
        payment_mandate_id=payload["mandateId"],
    )
    return signed_record


def log_validation_failed(
    *,
    reason: str,
    intent_mandate_id: str | None,
    cart_record: dict[str, Any] | None,
    action: str,
) -> None:
    signed_record = cart_record or create_audit_record(
        {
            "mandateType": "AP2AuditEvent",
            "mandateId": build_mandate_id("audit"),
            "agentId": AGENT_ID,
            "mode": "SIMULATION",
            "action": action,
            "reason": reason,
            "createdAt": utc_now_iso(),
        }
    )
    cart_id = None
    if cart_record and isinstance(cart_record.get("payload"), dict):
        cart_id = cart_record["payload"].get("mandateId")

    append_audit_event(
        event_type="MANDATE_VALIDATION_FAILED",
        final_action=action,
        status="FAILED",
        human_readable_reason=reason,
        signed_record=signed_record,
        intent_mandate_id=intent_mandate_id,
        cart_mandate_id=cart_id,
    )


def log_trade_blocked(
    *,
    reason: str,
    intent_mandate_id: str | None,
    cart_record: dict[str, Any] | None,
    action: str,
) -> None:
    signed_record = cart_record or create_audit_record(
        {
            "mandateType": "AP2AuditEvent",
            "mandateId": build_mandate_id("audit"),
            "agentId": AGENT_ID,
            "mode": "SIMULATION",
            "action": action,
            "reason": reason,
            "createdAt": utc_now_iso(),
        }
    )
    cart_id = None
    if cart_record and isinstance(cart_record.get("payload"), dict):
        cart_id = cart_record["payload"].get("mandateId")

    append_audit_event(
        event_type="SIMULATED_TRADE_BLOCKED",
        final_action="BLOCKED",
        status="BLOCKED",
        human_readable_reason=reason,
        signed_record=signed_record,
        intent_mandate_id=intent_mandate_id,
        cart_mandate_id=cart_id,
    )


def validate_cart_mandate(
    *,
    cart_record: dict[str, Any],
    expected_symbol: str,
    available_cash: float,
    available_btc: float,
) -> tuple[bool, str, dict[str, Any] | None]:
    active_intent, reason = load_active_intent_mandate()
    if active_intent is None:
        return False, reason, None

    valid, reason = verify_signed_record(cart_record)
    if not valid:
        return False, reason, active_intent

    payload = cart_record["payload"]
    action = str(payload.get("proposedAction", "")).upper()

    valid, reason = validate_intent_mandate(
        active_intent,
        expected_symbol=expected_symbol,
        expected_action=action,
    )
    if not valid:
        return False, reason, active_intent

    if payload.get("mandateType") != "CartMandate":
        return False, "Proposed mandate is not a Cart Mandate.", active_intent
    if payload.get("mode") != "SIMULATION":
        return False, "Cart Mandate is not in simulation mode.", active_intent
    if payload.get("symbol") != expected_symbol:
        return False, "Cart Mandate symbol does not match.", active_intent
    if payload.get("parentIntentMandateId") != active_intent["payload"].get("mandateId"):
        return False, "Cart Mandate does not reference the active Intent Mandate.", active_intent
    if is_expired(str(payload.get("expiresAt", ""))):
        return False, "Cart Mandate is expired.", active_intent

    try:
        price = float(payload.get("price", 0.0))
        quantity = float(payload.get("quantity", 0.0))
        notional_usd = float(payload.get("notionalUsd", 0.0))
    except (TypeError, ValueError):
        return False, "Cart Mandate price, quantity, or notional is invalid.", active_intent

    if price <= 0 or quantity <= 0 or notional_usd <= 0:
        return False, "Cart Mandate price, quantity, and notional must be positive.", active_intent

    rule_trigger = payload.get("ruleTrigger")
    if not isinstance(rule_trigger, dict):
        return False, "Cart Mandate rule trigger is missing.", active_intent

    intent_payload = active_intent["payload"]
    buy_rule = intent_payload.get("buyRule", {})
    sell_rule = intent_payload.get("sellRule", {})
    rounded_available_cash = round(float(available_cash), 2)
    rounded_available_btc = round(float(available_btc), 8)
    rounded_notional_usd = round(notional_usd, 2)
    rounded_quantity = round(quantity, 8)

    if action == "BUY":
        threshold = float(buy_rule.get("thresholdUsd", 0.0))
        previous_price = float(rule_trigger.get("previousPrice", 0.0))
        current_price = float(rule_trigger.get("currentPrice", 0.0))
        price_change_usd = float(rule_trigger.get("priceChangeUsd", 0.0))
        threshold_from_cart = float(rule_trigger.get("buyThresholdUsd", 0.0))

        if threshold <= 0 or threshold_from_cart != threshold:
            return False, "BUY Cart Mandate threshold does not match the Intent Mandate.", active_intent
        if price_change_usd >= 0:
            return False, "BUY Cart Mandate must represent a downward move.", active_intent
        if current_price > previous_price - threshold:
            return False, "BUY Cart Mandate does not satisfy the configured drop rule.", active_intent
        if rounded_available_cash + 0.01 < rounded_notional_usd:
            return False, "Not enough simulated cash for the BUY.", active_intent

    elif action == "SELL":
        threshold = float(sell_rule.get("thresholdUsd", 0.0))
        entry_price = float(rule_trigger.get("entryPrice", 0.0))
        current_price = float(rule_trigger.get("currentPrice", 0.0))
        rise_from_entry_usd = float(rule_trigger.get("riseFromEntryUsd", 0.0))
        threshold_from_cart = float(rule_trigger.get("sellThresholdUsd", 0.0))

        if threshold <= 0 or threshold_from_cart != threshold:
            return False, "SELL Cart Mandate threshold does not match the Intent Mandate.", active_intent
        if rise_from_entry_usd < threshold:
            return False, "SELL Cart Mandate does not satisfy the configured rise rule.", active_intent
        if current_price < entry_price + threshold:
            return False, "SELL Cart Mandate does not satisfy the configured sell rule.", active_intent
        if rounded_available_btc + 1e-8 < rounded_quantity:
            return False, "Not enough simulated BTC for the SELL.", active_intent

    else:
        return False, "Cart Mandate proposed action is invalid.", active_intent

    return True, "OK", active_intent


def run_self_test() -> dict[str, Any]:
    ensure_storage()
    intent = create_intent_mandate(
        symbol="BTCUSDT",
        starting_cash_usd=500.0,
        buy_cooldown_seconds=60,
        buy_threshold_usd=25.0,
        sell_threshold_usd=40.0,
    )
    intent_valid, intent_reason = validate_intent_mandate(
        intent,
        expected_symbol="BTCUSDT",
        expected_action="BUY",
    )
    cart = create_cart_mandate(
        intent_record=intent,
        action="BUY",
        symbol="BTCUSDT",
        price=78000.0,
        quantity=0.00641026,
        notional_usd=500.0,
        ai_signal="HOLD",
        ai_confidence=42,
        rule_trigger={
            "previousPrice": 78030.0,
            "currentPrice": 78000.0,
            "priceChangeUsd": -30.0,
            "buyThresholdUsd": 25.0,
        },
        reason="Self-test BUY proposal.",
    )
    cart_valid, cart_reason, active_intent = validate_cart_mandate(
        cart_record=cart,
        expected_symbol="BTCUSDT",
        available_cash=500.0,
        available_btc=0.0,
    )
    payment = create_payment_mandate(
        intent_record=active_intent or intent,
        cart_record=cart,
        action="BUY",
        symbol="BTCUSDT",
        execution_price=78000.0,
        quantity=0.00641026,
        notional_usd=500.0,
        cash_before=500.0,
        cash_after=0.0,
        btc_before=0.0,
        btc_after=0.00641026,
        reason="Self-test simulated BUY execution.",
    )
    return {
        "intentMandateId": intent["payload"]["mandateId"],
        "intentValid": intent_valid,
        "intentReason": intent_reason,
        "cartMandateId": cart["payload"]["mandateId"],
        "cartValid": cart_valid,
        "cartReason": cart_reason,
        "paymentMandateId": payment["payload"]["mandateId"],
        "paymentSignatureVerified": verify_signed_record(payment)[0],
    }


def b64encode_bytes(value: bytes) -> str:
    return b64encode(value).decode("ascii")


def b64decode_text(value: str) -> bytes:
    return b64decode(value.encode("ascii"))


def generate_ecdsa_key_pair() -> dict[str, str]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return {"privateKeyPem": private_pem, "publicKeyPem": public_pem}


def load_identity_registry() -> dict[str, Any]:
    ensure_storage()
    registry = load_json(AP2_IDENTITIES_PATH)
    if not registry or not isinstance(registry.get("participants"), dict):
        return {"participants": {}}
    return registry


def save_identity_registry(registry: dict[str, Any]) -> bool:
    return save_json(AP2_IDENTITIES_PATH, registry)


def register_participant(
    *,
    participant_type: str,
    participant_id: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    participant_type = participant_type.strip().lower()
    if participant_type not in {"user", "merchant", "agent"}:
        raise ValueError("participant_type must be user, merchant, or agent.")
    if not participant_id.strip():
        raise ValueError("participant_id is required.")

    key_pair = generate_ecdsa_key_pair()
    participant = {
        "participantId": participant_id,
        "participantType": participant_type,
        "displayName": display_name or participant_id,
        "keyAlgorithm": "ECDSA_P256_SHA256",
        "publicKeyPem": key_pair["publicKeyPem"],
        "privateKeyPem": key_pair["privateKeyPem"],
        "createdAt": utc_now_iso(),
    }
    registry = load_identity_registry()
    registry["participants"][participant_id] = participant
    save_identity_registry(registry)
    return participant


def get_participant(participant_id: str) -> dict[str, Any]:
    participant = load_identity_registry()["participants"].get(participant_id)
    if not isinstance(participant, dict):
        raise ValueError(f"Participant is not registered: {participant_id}")
    return participant


def get_or_register_participant(participant_type: str, participant_id: str) -> dict[str, Any]:
    try:
        return get_participant(participant_id)
    except ValueError:
        return register_participant(
            participant_type=participant_type,
            participant_id=participant_id,
            display_name=participant_id,
        )


def sign_payload_with_private_key(payload: dict[str, Any], private_key_pem: str) -> str:
    private_key = serialization.load_pem_private_key(private_key_pem.encode("ascii"), password=None)
    signature = private_key.sign(canonical_json(payload).encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    return b64encode_bytes(signature)


def verify_payload_with_public_key(payload: dict[str, Any], signature: str, public_key_pem: str) -> tuple[bool, str]:
    public_key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
    try:
        public_key.verify(b64decode_text(signature), canonical_json(payload).encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):
        return False, "ECDSA signature verification failed."
    return True, "OK"


def create_ecdsa_signed_record(payload: dict[str, Any], signer_id: str) -> dict[str, Any]:
    participant = get_participant(signer_id)
    payload_hash = compute_payload_hash(payload)
    return {
        "payload": payload,
        "payloadHash": payload_hash,
        "signatureAlgorithm": "ECDSA_P256_SHA256",
        "signerId": signer_id,
        "signature": sign_payload_with_private_key(payload, str(participant["privateKeyPem"])),
    }


def verify_ecdsa_signed_record(
    record: dict[str, Any],
    *,
    expected_signer_id: str | None = None,
    expected_participant_type: str | None = None,
) -> tuple[bool, str]:
    if not isinstance(record, dict):
        return False, "Signed record is not a JSON object."

    payload = record.get("payload")
    payload_hash = record.get("payloadHash")
    signer_id = record.get("signerId")
    signature = record.get("signature")
    if not isinstance(payload, dict):
        return False, "Signed record payload is missing or invalid."
    if compute_payload_hash(payload) != payload_hash:
        return False, "Payload hash verification failed."
    if not isinstance(signer_id, str) or not signer_id:
        return False, "Signed record signerId is missing."
    if expected_signer_id is not None and signer_id != expected_signer_id:
        return False, "Signed record signer does not match."
    if not isinstance(signature, str) or not signature:
        return False, "Signed record signature is missing."

    try:
        participant = get_participant(signer_id)
    except ValueError as exc:
        return False, str(exc)
    if expected_participant_type is not None and participant.get("participantType") != expected_participant_type:
        return False, "Signed record participant type does not match."

    return verify_payload_with_public_key(payload, signature, str(participant["publicKeyPem"]))


def normalize_categories(categories: list[str]) -> list[str]:
    normalized = sorted({category.strip().lower() for category in categories if category.strip()})
    if not normalized:
        raise ValueError("At least one category is required.")
    return normalized


def create_shopping_intent_mandate(
    *,
    user_id: str,
    maximum_spending_amount: float,
    currency: str,
    allowed_categories: list[str],
    human_approval_required: bool,
) -> dict[str, Any]:
    get_participant(user_id)
    if maximum_spending_amount <= 0:
        raise ValueError("maximum_spending_amount must be positive.")
    payload = {
        "mandateType": "IntentMandate",
        "mandateId": build_mandate_id("intent"),
        "userId": user_id,
        "mode": "SIMULATION",
        "maximumSpendingAmount": round(maximum_spending_amount, 2),
        "currency": currency.upper(),
        "allowedPurchaseCategories": normalize_categories(allowed_categories),
        "humanApprovalRequired": bool(human_approval_required),
        "createdAt": utc_now_iso(),
        "expiresAt": iso_after(hours=24),
    }
    record = create_ecdsa_signed_record(payload, user_id)
    append_audit_event(
        event_type="SHOPPING_INTENT_MANDATE_CREATED",
        final_action="AUTHORIZE",
        status="ACTIVE",
        human_readable_reason="User created a signed shopping Intent Mandate.",
        signed_record=record,
        intent_mandate_id=payload["mandateId"],
    )
    return record


def calculate_cart_total(items: list[dict[str, Any]]) -> float:
    total = 0.0
    for item in items:
        total += float(item.get("unitPrice", 0.0)) * int(item.get("quantity", 1))
    return round(total, 2)


def normalize_cart_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        raise ValueError("At least one cart item is required.")
    normalized_items = []
    for item in items:
        name = str(item.get("name", "")).strip()
        category = str(item.get("category", "")).strip().lower()
        quantity = int(item.get("quantity", 1))
        unit_price = float(item.get("unitPrice", 0.0))
        if not name:
            raise ValueError("Cart item name is required.")
        if not category:
            raise ValueError("Cart item category is required.")
        if quantity <= 0 or unit_price <= 0:
            raise ValueError("Cart item quantity and unitPrice must be positive.")
        normalized_items.append(
            {
                "name": name,
                "category": category,
                "quantity": quantity,
                "unitPrice": round(unit_price, 2),
                "lineTotal": round(quantity * unit_price, 2),
            }
        )
    return normalized_items


def create_shopping_cart_mandate(
    *,
    merchant_id: str,
    intent_record: dict[str, Any],
    items: list[dict[str, Any]],
    currency: str,
) -> dict[str, Any]:
    get_participant(merchant_id)
    valid, reason = verify_ecdsa_signed_record(intent_record, expected_participant_type="user")
    if not valid:
        raise ValueError(f"Intent Mandate is invalid: {reason}")

    intent_payload = intent_record["payload"]
    normalized_items = normalize_cart_items(items)
    total_amount = calculate_cart_total(normalized_items)
    payload = {
        "mandateType": "CartMandate",
        "mandateId": build_mandate_id("cart"),
        "parentIntentMandateId": intent_payload["mandateId"],
        "userId": intent_payload["userId"],
        "merchantId": merchant_id,
        "mode": "SIMULATION",
        "items": normalized_items,
        "totalAmount": total_amount,
        "currency": currency.upper(),
        "createdAt": utc_now_iso(),
        "expiresAt": iso_after(seconds=900),
    }
    record = create_ecdsa_signed_record(payload, merchant_id)
    append_audit_event(
        event_type="SHOPPING_CART_MANDATE_CREATED",
        final_action="PROPOSE_PAYMENT",
        status="PROPOSED",
        human_readable_reason="Merchant created a signed Cart Mandate.",
        signed_record=record,
        intent_mandate_id=intent_payload["mandateId"],
        cart_mandate_id=payload["mandateId"],
    )
    return record


def create_cart_approval_payload(cart_record: dict[str, Any], user_id: str) -> dict[str, Any]:
    cart_payload = cart_record["payload"]
    return {
        "approvalType": "CartUserApproval",
        "approvalId": build_mandate_id("approval"),
        "userId": user_id,
        "cartMandateId": cart_payload["mandateId"],
        "cartPayloadHash": cart_record["payloadHash"],
        "approvedAt": utc_now_iso(),
    }


def approve_shopping_cart(cart_record: dict[str, Any], *, user_id: str) -> dict[str, Any]:
    valid, reason = verify_ecdsa_signed_record(cart_record, expected_participant_type="merchant")
    if not valid:
        raise ValueError(f"Cart Mandate is invalid: {reason}")
    if cart_record["payload"].get("userId") != user_id:
        raise ValueError("Cart Mandate user does not match the approving user.")

    approval_payload = create_cart_approval_payload(cart_record, user_id)
    approved_record = dict(cart_record)
    approved_record["userApproval"] = create_ecdsa_signed_record(approval_payload, user_id)
    append_audit_event(
        event_type="SHOPPING_CART_APPROVED",
        final_action="APPROVE",
        status="APPROVED",
        human_readable_reason="User approved the Cart Mandate with an ECDSA signature.",
        signed_record=approved_record,
        intent_mandate_id=cart_record["payload"].get("parentIntentMandateId"),
        cart_mandate_id=cart_record["payload"].get("mandateId"),
    )
    return approved_record


def create_shopping_payment_mandate(
    *,
    agent_id: str,
    cart_record: dict[str, Any],
    amount: float,
    currency: str,
    payment_method: str,
    human_present: bool,
) -> dict[str, Any]:
    get_participant(agent_id)
    valid, reason = verify_ecdsa_signed_record(cart_record, expected_participant_type="merchant")
    if not valid:
        raise ValueError(f"Cart Mandate is invalid: {reason}")

    cart_payload = cart_record["payload"]
    payload = {
        "mandateType": "PaymentMandate",
        "mandateId": build_mandate_id("payment"),
        "parentCartMandateId": cart_payload["mandateId"],
        "parentIntentMandateId": cart_payload["parentIntentMandateId"],
        "agentId": agent_id,
        "userId": cart_payload["userId"],
        "merchantId": cart_payload["merchantId"],
        "mode": "SIMULATION",
        "amount": round(amount, 2),
        "currency": currency.upper(),
        "paymentMethod": payment_method,
        "humanPresent": bool(human_present),
        "realMoneyMoved": False,
        "createdAt": utc_now_iso(),
    }
    record = create_ecdsa_signed_record(payload, agent_id)
    append_audit_event(
        event_type="SHOPPING_PAYMENT_MANDATE_CREATED",
        final_action="PAY",
        status="PROPOSED",
        human_readable_reason="Agent created a signed Payment Mandate.",
        signed_record=record,
        intent_mandate_id=payload["parentIntentMandateId"],
        cart_mandate_id=payload["parentCartMandateId"],
        payment_mandate_id=payload["mandateId"],
    )
    return record


def validate_cart_user_approval(cart_record: dict[str, Any], intent_payload: dict[str, Any]) -> tuple[bool, str]:
    if not intent_payload.get("humanApprovalRequired"):
        return True, "OK"

    approval_record = cart_record.get("userApproval")
    if not isinstance(approval_record, dict):
        return False, "User approval is required but missing."

    valid, reason = verify_ecdsa_signed_record(
        approval_record,
        expected_signer_id=str(intent_payload["userId"]),
        expected_participant_type="user",
    )
    if not valid:
        return False, f"User approval signature is invalid: {reason}"

    approval_payload = approval_record["payload"]
    if approval_payload.get("cartMandateId") != cart_record["payload"].get("mandateId"):
        return False, "User approval does not reference this Cart Mandate."
    if approval_payload.get("cartPayloadHash") != cart_record.get("payloadHash"):
        return False, "User approval does not bind to this Cart Mandate payload."
    return True, "OK"


def validate_payment_chain(
    *,
    payment_record: dict[str, Any],
    cart_record: dict[str, Any],
    intent_record: dict[str, Any],
) -> tuple[bool, list[str]]:
    failures: list[str] = []

    valid, reason = verify_ecdsa_signed_record(payment_record, expected_participant_type="agent")
    if not valid:
        failures.append(f"Payment signature invalid: {reason}")
    valid, reason = verify_ecdsa_signed_record(cart_record, expected_participant_type="merchant")
    if not valid:
        failures.append(f"Cart signature invalid: {reason}")
    valid, reason = verify_ecdsa_signed_record(intent_record, expected_participant_type="user")
    if not valid:
        failures.append(f"Intent signature invalid: {reason}")
    if failures:
        return False, failures

    payment = payment_record["payload"]
    cart = cart_record["payload"]
    intent = intent_record["payload"]

    if payment.get("parentCartMandateId") != cart.get("mandateId"):
        failures.append("Payment Mandate does not link to the Cart Mandate.")
    if cart.get("parentIntentMandateId") != intent.get("mandateId"):
        failures.append("Cart Mandate does not link to the Intent Mandate.")
    if payment.get("parentIntentMandateId") != intent.get("mandateId"):
        failures.append("Payment Mandate does not link to the Intent Mandate.")
    if cart.get("userId") != intent.get("userId") or payment.get("userId") != intent.get("userId"):
        failures.append("User identity is inconsistent across the mandate chain.")

    approval_valid, approval_reason = validate_cart_user_approval(cart_record, intent)
    if not approval_valid:
        failures.append(approval_reason)

    cart_total = round(float(cart.get("totalAmount", 0.0)), 2)
    max_spend = round(float(intent.get("maximumSpendingAmount", 0.0)), 2)
    if cart_total > max_spend:
        failures.append("Cart total exceeds the user spending limit.")
    if round(float(payment.get("amount", 0.0)), 2) != cart_total:
        failures.append("Payment amount does not match the Cart Mandate total.")
    if payment.get("currency") != cart.get("currency") or cart.get("currency") != intent.get("currency"):
        failures.append("Currency is inconsistent across the mandate chain.")

    allowed_categories = set(intent.get("allowedPurchaseCategories", []))
    for item in cart.get("items", []):
        if str(item.get("category", "")).lower() not in allowed_categories:
            failures.append(f"Item category is not allowed: {item.get('category')}")

    return not failures, failures or ["OK"]


def run_default_payment_chain_simulation() -> dict[str, Any]:
    user = get_or_register_participant("user", "demo_user")
    merchant = get_or_register_participant("merchant", "demo_merchant")
    agent = get_or_register_participant("agent", "demo_agent")

    intent = create_shopping_intent_mandate(
        user_id=user["participantId"],
        maximum_spending_amount=100.0,
        currency="USD",
        allowed_categories=["books", "software"],
        human_approval_required=True,
    )
    cart = create_shopping_cart_mandate(
        merchant_id=merchant["participantId"],
        intent_record=intent,
        currency="USD",
        items=[
            {"name": "Python ebook", "category": "books", "quantity": 1, "unitPrice": 24.99},
            {"name": "Editor plugin", "category": "software", "quantity": 1, "unitPrice": 19.99},
        ],
    )
    approved_cart = approve_shopping_cart(cart, user_id=user["participantId"])
    payment = create_shopping_payment_mandate(
        agent_id=agent["participantId"],
        cart_record=approved_cart,
        amount=approved_cart["payload"]["totalAmount"],
        currency="USD",
        payment_method="simulated_card",
        human_present=True,
    )
    valid, messages = validate_payment_chain(
        payment_record=payment,
        cart_record=approved_cart,
        intent_record=intent,
    )

    over_budget_cart = create_shopping_cart_mandate(
        merchant_id=merchant["participantId"],
        intent_record=intent,
        currency="USD",
        items=[{"name": "Expensive course", "category": "software", "quantity": 1, "unitPrice": 150.0}],
    )
    over_budget_cart = approve_shopping_cart(over_budget_cart, user_id=user["participantId"])
    over_budget_payment = create_shopping_payment_mandate(
        agent_id=agent["participantId"],
        cart_record=over_budget_cart,
        amount=over_budget_cart["payload"]["totalAmount"],
        currency="USD",
        payment_method="simulated_card",
        human_present=True,
    )
    over_budget_valid, over_budget_messages = validate_payment_chain(
        payment_record=over_budget_payment,
        cart_record=over_budget_cart,
        intent_record=intent,
    )

    bad_category_cart = create_shopping_cart_mandate(
        merchant_id=merchant["participantId"],
        intent_record=intent,
        currency="USD",
        items=[{"name": "Concert ticket", "category": "entertainment", "quantity": 1, "unitPrice": 20.0}],
    )
    bad_category_cart = approve_shopping_cart(bad_category_cart, user_id=user["participantId"])
    bad_category_payment = create_shopping_payment_mandate(
        agent_id=agent["participantId"],
        cart_record=bad_category_cart,
        amount=bad_category_cart["payload"]["totalAmount"],
        currency="USD",
        payment_method="simulated_card",
        human_present=True,
    )
    bad_category_valid, bad_category_messages = validate_payment_chain(
        payment_record=bad_category_payment,
        cart_record=bad_category_cart,
        intent_record=intent,
    )

    no_approval_intent = create_shopping_intent_mandate(
        user_id=user["participantId"],
        maximum_spending_amount=50.0,
        currency="USD",
        allowed_categories=["software"],
        human_approval_required=False,
    )
    no_human_cart = create_shopping_cart_mandate(
        merchant_id=merchant["participantId"],
        intent_record=no_approval_intent,
        currency="USD",
        items=[{"name": "Automation script", "category": "software", "quantity": 1, "unitPrice": 12.0}],
    )
    no_human_payment = create_shopping_payment_mandate(
        agent_id=agent["participantId"],
        cart_record=no_human_cart,
        amount=no_human_cart["payload"]["totalAmount"],
        currency="USD",
        payment_method="simulated_wallet",
        human_present=False,
    )
    no_human_valid, no_human_messages = validate_payment_chain(
        payment_record=no_human_payment,
        cart_record=no_human_cart,
        intent_record=no_approval_intent,
    )

    return {
        "registeredParticipants": [
            user["participantId"],
            merchant["participantId"],
            agent["participantId"],
        ],
        "happyPathValid": valid,
        "happyPathMessages": messages,
        "humanPresentFlow": payment["payload"]["humanPresent"],
        "humanNotPresentFlowValid": no_human_valid,
        "humanNotPresentMessages": no_human_messages,
        "overBudgetRejected": not over_budget_valid,
        "overBudgetMessages": over_budget_messages,
        "badCategoryRejected": not bad_category_valid,
        "badCategoryMessages": bad_category_messages,
    }


def run_checkout_scenario(
    *,
    user_id: str,
    merchant_id: str,
    agent_id: str,
    maximum_spending_amount: float,
    currency: str,
    allowed_categories: list[str],
    items: list[dict[str, Any]],
    human_approval_required: bool,
    approve_cart: bool,
    human_present: bool,
    payment_method: str,
) -> dict[str, Any]:
    user = get_or_register_participant("user", user_id)
    merchant = get_or_register_participant("merchant", merchant_id)
    agent = get_or_register_participant("agent", agent_id)
    intent = create_shopping_intent_mandate(
        user_id=user["participantId"],
        maximum_spending_amount=maximum_spending_amount,
        currency=currency,
        allowed_categories=allowed_categories,
        human_approval_required=human_approval_required,
    )
    cart = create_shopping_cart_mandate(
        merchant_id=merchant["participantId"],
        intent_record=intent,
        currency=currency,
        items=items,
    )
    if approve_cart:
        cart = approve_shopping_cart(cart, user_id=user["participantId"])

    payment = create_shopping_payment_mandate(
        agent_id=agent["participantId"],
        cart_record=cart,
        amount=cart["payload"]["totalAmount"],
        currency=currency,
        payment_method=payment_method,
        human_present=human_present,
    )
    valid, messages = validate_payment_chain(
        payment_record=payment,
        cart_record=cart,
        intent_record=intent,
    )
    return {
        "valid": valid,
        "messages": messages,
        "registeredParticipants": [
            user["participantId"],
            merchant["participantId"],
            agent["participantId"],
        ],
        "intentMandateId": intent["payload"]["mandateId"],
        "cartMandateId": cart["payload"]["mandateId"],
        "paymentMandateId": payment["payload"]["mandateId"],
        "cartTotal": cart["payload"]["totalAmount"],
        "currency": cart["payload"]["currency"],
        "humanApprovalRequired": intent["payload"]["humanApprovalRequired"],
        "cartApproved": isinstance(cart.get("userApproval"), dict),
        "humanPresent": payment["payload"]["humanPresent"],
        "intent": intent,
        "cart": cart,
        "payment": payment,
    }


def prompt_csv(prompt: str) -> list[str]:
    return [part.strip() for part in input(prompt).split(",") if part.strip()]


def run_interactive_checkout_cli() -> dict[str, Any]:
    print("AP2 SIM | Interactive ECDSA checkout simulation")
    user_id = input("User ID: ").strip() or "cli_user"
    merchant_id = input("Merchant ID: ").strip() or "cli_merchant"
    agent_id = input("Agent ID: ").strip() or "cli_agent"
    budget = float(input("Maximum spending amount: ").strip() or "100")
    currency = (input("Currency [USD]: ").strip() or "USD").upper()
    categories = normalize_categories(prompt_csv("Allowed categories (comma-separated): "))
    approval_required = (input("Require human approval? [y/N]: ").strip().lower() in {"y", "yes"})

    get_or_register_participant("user", user_id)
    get_or_register_participant("merchant", merchant_id)
    get_or_register_participant("agent", agent_id)
    intent = create_shopping_intent_mandate(
        user_id=user_id,
        maximum_spending_amount=budget,
        currency=currency,
        allowed_categories=categories,
        human_approval_required=approval_required,
    )

    items: list[dict[str, Any]] = []
    while True:
        name = input("Item name (blank to finish): ").strip()
        if not name:
            break
        category = input("Item category: ").strip()
        quantity = int(input("Quantity [1]: ").strip() or "1")
        unit_price = float(input("Unit price: ").strip())
        items.append({"name": name, "category": category, "quantity": quantity, "unitPrice": unit_price})

    cart = create_shopping_cart_mandate(
        merchant_id=merchant_id,
        intent_record=intent,
        items=items,
        currency=currency,
    )
    if approval_required:
        cart = approve_shopping_cart(cart, user_id=user_id)

    human_present = input("Was a human present for payment? [y/N]: ").strip().lower() in {"y", "yes"}
    payment = create_shopping_payment_mandate(
        agent_id=agent_id,
        cart_record=cart,
        amount=cart["payload"]["totalAmount"],
        currency=currency,
        payment_method=input("Payment method [simulated_card]: ").strip() or "simulated_card",
        human_present=human_present,
    )
    valid, messages = validate_payment_chain(payment_record=payment, cart_record=cart, intent_record=intent)
    result = {"valid": valid, "messages": messages, "intent": intent, "cart": cart, "payment": payment}
    print(json.dumps({"valid": valid, "messages": messages}, indent=2))
    return result


ensure_storage()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run AP2-inspired local simulations.")
    parser.add_argument("--shopping-demo", action="store_true", help="Run the default ECDSA shopping-chain demo.")
    parser.add_argument("--interactive-checkout", action="store_true", help="Run an interactive ECDSA checkout scenario.")
    args = parser.parse_args()

    if args.interactive_checkout:
        run_interactive_checkout_cli()
    elif args.shopping_demo:
        print(json.dumps(run_default_payment_chain_simulation(), indent=2))
    else:
        print(json.dumps(run_self_test(), indent=2))
