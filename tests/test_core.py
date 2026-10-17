import json
import os
import unittest
from typing import Any, Dict, List, Optional, Union
from unittest import mock

from gamebanking import (
    APIConnectionError,
    ConflictError,
    FeeChangedError,
    GameBank,
    PenaltyChangedError,
    GameBankError,
    InsufficientFundsError,
    RawResponse,
    ServerError,
    WebhookVerificationError,
    format_minor,
    to_minor,
    verify_webhook,
)

Reply = Union[Dict[str, Any], Exception]


class FakeSender:
    """Returns scripted replies in order and records each call."""

    def __init__(self, replies: List[Reply]) -> None:
        self.replies = list(replies)
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, method: str, url: str, headers: Dict[str, str], body: Optional[bytes], timeout: float) -> RawResponse:
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        payload = r.get("body", {})
        raw = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
        headers_out = {"content-type": "application/json", **{k.lower(): v for k, v in r.get("headers", {}).items()}}
        return RawResponse(r["status"], headers_out, raw)


def client(sender: FakeSender, **kw: Any) -> GameBank:
    gb = GameBank(api_key="gbe_test_sk_abc", base_url="http://engine.test/", sender=sender, **kw)
    gb._t._sleep = lambda _s: None  # no real waiting in unit tests
    return gb


def err(status: int, code: str, **details: Any) -> Dict[str, Any]:
    return {"status": status, "body": {"error": {"code": code, "message": code, "details": details, "correlation_id": "req_1"}}}


TRANSFER = {"status": 201, "body": {"transaction": {"id": "t1"}, "source_balance": {}}}


class ConfigurationTest(unittest.TestCase):
    def test_environment_and_url(self) -> None:
        s = FakeSender([{"status": 200, "body": {"mode": "manual"}}])
        gb = client(s)
        self.assertEqual(gb.environment, "sandbox")
        gb.clock.get()
        self.assertEqual(s.calls[0]["url"], "http://engine.test/v1/clock")
        self.assertEqual(s.calls[0]["headers"]["Authorization"], "Bearer gbe_test_sk_abc")
        self.assertEqual(GameBank(api_key="gbe_live_sk_x", base_url="http://e").environment, "production")

    def test_requires_key_and_url_with_env_fallback(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(GameBankError) as c:
                GameBank(base_url="http://e")
            self.assertEqual(c.exception.code, "missing_api_key")
            with self.assertRaises(GameBankError) as c:
                GameBank(api_key="gbe_test_sk_x")
            self.assertEqual(c.exception.code, "missing_base_url")
        with mock.patch.dict(os.environ, {"GBE_API_KEY": "gbe_live_sk_env", "GBE_BASE_URL": "http://env"}, clear=True):
            self.assertEqual(GameBank().environment, "production")


class RetryTest(unittest.TestCase):
    def test_one_idempotency_key_reused_across_retries(self) -> None:
        s = FakeSender([ConnectionResetError("reset"), {"status": 503, "body": {}}, TRANSFER])
        r = client(s).transfers.create(source_account_id="a", destination_account_id="b", amount_minor=100)
        self.assertEqual(r["transaction"]["id"], "t1")
        keys = {c["headers"]["Idempotency-Key"] for c in s.calls}
        self.assertEqual(len(s.calls), 3)
        self.assertEqual(len(keys), 1)
        self.assertTrue(next(iter(keys)).startswith("sdk_"))

    def test_callers_key_is_used(self) -> None:
        s = FakeSender([TRANSFER])
        client(s).transfers.create(source_account_id="a", destination_account_id="b", amount_minor=1, idempotency_key="order-42")
        self.assertEqual(s.calls[0]["headers"]["Idempotency-Key"], "order-42")

    def test_plain_post_is_not_retried_after_it_may_have_arrived(self) -> None:
        for first in (ConnectionResetError("reset"), {"status": 502, "body": {}}):
            s = FakeSender([first, {"status": 201, "body": {}}])
            with self.assertRaises(GameBankError):
                client(s).accounts.open(bank_id="b", player_id="p")
            self.assertEqual(len(s.calls), 1)
            self.assertNotIn("Idempotency-Key", s.calls[0]["headers"])

    def test_rate_limit_retried_with_retry_after(self) -> None:
        waits: List[float] = []
        s = FakeSender([{"status": 429, "body": {"error": {"code": "rate_limited"}}, "headers": {"Retry-After": "3"}}, {"status": 201, "body": {"id": "acc"}}])
        gb = client(s)
        gb._t._sleep = waits.append
        self.assertEqual(gb.accounts.open(bank_id="b", player_id="p")["id"], "acc")
        self.assertEqual(waits, [3.0])

    def test_gets_and_upserts_retry_after_network_errors(self) -> None:
        s = FakeSender([ConnectionResetError(), {"status": 200, "body": {"id": "p1"}}, TimeoutError(), {"status": 200, "body": {"id": "p2"}}])
        gb = client(s)
        self.assertEqual(gb.players.get("p1")["id"], "p1")
        self.assertEqual(gb.players.upsert(external_player_id="x")["id"], "p2")
        self.assertEqual(len(s.calls), 4)

    def test_stops_after_max_retries(self) -> None:
        s = FakeSender([{"status": 500, "body": {}}, {"status": 500, "body": {}}])
        with self.assertRaises(ServerError):
            client(s, max_retries=1).accounts.balance("a")
        self.assertEqual(len(s.calls), 2)

    def test_request_in_progress_retried_for_keyed_requests(self) -> None:
        s = FakeSender([err(409, "request_in_progress"), TRANSFER])
        client(s).transfers.create(source_account_id="a", destination_account_id="b", amount_minor=1)
        self.assertEqual(len(s.calls), 2)


class ErrorTest(unittest.TestCase):
    def test_typed_errors_with_details(self) -> None:
        s = FakeSender([err(422, "insufficient_funds", available_balance=5, requested_amount=9)])
        with self.assertRaises(InsufficientFundsError) as c:
            client(s).transfers.create(source_account_id="a", destination_account_id="b", amount_minor=9)
        self.assertEqual(c.exception.status, 422)
        self.assertEqual(c.exception.details["available_balance"], 5)
        self.assertEqual(c.exception.request_id, "req_1")
        with self.assertRaises(ConflictError) as c:
            client(FakeSender([err(409, "idempotency_key_reused")])).transfers.create(
                source_account_id="a", destination_account_id="b", amount_minor=9)
        self.assertNotIsInstance(c.exception, FeeChangedError)
        s = FakeSender([err(409, "fee_changed", fees_total_minor=70, max_fee_minor=60)])
        with self.assertRaises(FeeChangedError) as c:
            client(s).transfers.create(source_account_id="a", destination_account_id="b", amount_minor=9, max_fee_minor=60)
        self.assertEqual(c.exception.details["fees_total_minor"], 70)
        self.assertIn(b'"max_fee_minor":60', s.calls[0]["body"])

    def test_connection_error_after_retries(self) -> None:
        s = FakeSender([ConnectionRefusedError(), ConnectionRefusedError()])
        with self.assertRaises(APIConnectionError) as c:
            client(s, max_retries=1).clock.get()
        self.assertEqual(c.exception.status, 0)

    def test_html_instead_of_engine(self) -> None:
        s = FakeSender([{"status": 200, "body": "<!doctype html>", "headers": {"Content-Type": "text/html"}}])
        with self.assertRaises(GameBankError) as c:
            client(s).clock.get()
        self.assertEqual(c.exception.code, "invalid_response")
        self.assertIn("base_url", c.exception.message)

    def test_non_integer_amount_rejected_before_sending(self) -> None:
        s = FakeSender([])
        with self.assertRaises(TypeError):
            client(s).funding.create(account_id="a", amount_minor=10.5, reason="r", reference="x")  # type: ignore[arg-type]
        self.assertEqual(s.calls, [])


class MoneyTest(unittest.TestCase):
    def test_round_trip_without_floats(self) -> None:
        self.assertEqual(to_minor("100.50", 2), 10050)
        self.assertEqual(to_minor("1,234.5", 2), 123450)
        self.assertEqual(to_minor("0.07", 2), 7)
        self.assertEqual(to_minor("42", 0), 42)
        self.assertEqual(to_minor("-3.2", 1), -32)
        self.assertEqual(format_minor(10050, 2), "100.50")
        self.assertEqual(format_minor(7, 2), "0.07")
        self.assertEqual(format_minor(-5, 3), "-0.005")
        self.assertEqual(format_minor(42, 0), "42")
        for bad in ("1.005", "abc"):
            with self.assertRaises(ValueError):
                to_minor(bad, 2)
        with self.assertRaises(TypeError):
            to_minor(1.5, 2)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()


class WebhookVerifyTest(unittest.TestCase):
    # The engine's published test vector (docs/webhooks.md).
    BODY = b'{"hello":"world"}'
    VECTOR = "f592bbf3951cfc94e560eecfb5d9dd4da6b0fff2e626235f8ab4b54860925d0b"
    NOW = 1_700_000_010

    @staticmethod
    def sign(secret: str, ts: int, body: bytes) -> str:
        import hashlib
        import hmac
        return hmac.new(secret.encode(), str(ts).encode() + b"." + body, hashlib.sha256).hexdigest()

    def reason(self, *args: Any, **kw: Any) -> str:
        with self.assertRaises(WebhookVerificationError) as c:
            verify_webhook(*args, **kw)
        return c.exception.reason

    def test_vector_and_parsed_event(self) -> None:
        h = f"t=1700000000,v1={self.VECTOR}"
        self.assertEqual(verify_webhook(self.BODY, h, "whsec_test", now=self.NOW), {"hello": "world"})
        self.assertEqual(verify_webhook(self.BODY.decode(), h, "whsec_test", now=self.NOW), {"hello": "world"})

    def test_any_signature_and_any_secret(self) -> None:
        h = f"t=1700000000,v1={self.sign('whsec_new', 1_700_000_000, self.BODY)},v1={self.VECTOR}"
        verify_webhook(self.BODY, h, "whsec_new", now=self.NOW)
        verify_webhook(self.BODY, h, "whsec_test", now=self.NOW)
        verify_webhook(self.BODY, f"t=1700000000,v1={self.VECTOR}", ["whsec_other", "whsec_test"], now=self.NOW)

    def test_rejections(self) -> None:
        h = f"t=1700000000,v1={self.VECTOR}"
        self.assertEqual(self.reason(b'{"hello":"world!"}', h, "whsec_test", now=self.NOW), "no_matching_signature")
        self.assertEqual(self.reason(self.BODY, h, "whsec_wrong", now=self.NOW), "no_matching_signature")
        self.assertEqual(self.reason(self.BODY, h, "whsec_test", now=1_700_000_301), "timestamp_out_of_tolerance")
        self.assertEqual(self.reason(self.BODY, h, "whsec_test", now=1_699_999_000), "timestamp_out_of_tolerance")
        verify_webhook(self.BODY, h, "whsec_test", now=1_700_000_900, tolerance=1_000)
        self.assertEqual(self.reason(self.BODY, f"v1={self.VECTOR}", "whsec_test", now=self.NOW), "malformed_header")
        self.assertEqual(self.reason(self.BODY, None, "whsec_test", now=self.NOW), "malformed_header")
        self.assertEqual(self.reason(self.BODY, "t=1700000000,v1=zz\u00e9", "whsec_test", now=self.NOW), "malformed_header")
        text = b"plain text"
        self.assertEqual(self.reason(text, f"t=1700000000,v1={self.sign('s', 1_700_000_000, text)}", "s", now=self.NOW), "invalid_payload")


class WebhooksResourceTest(unittest.TestCase):
    def test_routes(self) -> None:
        s = FakeSender([
            {"status": 201, "body": {"id": "e1", "secret": "whsec_x"}},
            {"status": 200, "body": {"data": [{"id": "ev1"}], "next_cursor": "c2", "has_more": True}},
            {"status": 200, "body": {"data": [{"id": "ev2"}], "next_cursor": None, "has_more": False}},
            {"status": 202, "body": {"data": []}},
            {"status": 204, "body": ""},
        ])
        gb = client(s)
        self.assertEqual(gb.webhooks.endpoints.create(url="https://hooks.example.com", event_types=["account.debited"])["secret"], "whsec_x")
        ids = [e["id"] for e in gb.webhooks.events.iter(type="account.debited", account_id="a1")]
        gb.webhooks.events.redeliver("ev1", endpoint_id="e1")
        gb.webhooks.endpoints.delete("e1")
        self.assertEqual(ids, ["ev1", "ev2"])
        paths = [f"{c['method']} {c['url'].split('engine.test', 1)[1]}" for c in s.calls]
        self.assertEqual(paths, [
            "POST /v1/webhooks/endpoints",
            "GET /v1/webhooks/events?type=account.debited&account_id=a1",
            "GET /v1/webhooks/events?type=account.debited&account_id=a1&cursor=c2",
            "POST /v1/webhooks/events/ev1/redeliver",
            "DELETE /v1/webhooks/endpoints/e1",
        ])
        self.assertEqual(json.loads(s.calls[0]["body"]), {"url": "https://hooks.example.com", "event_types": ["account.debited"]})


class CardsTest(unittest.TestCase):
    def test_decline_is_a_result_and_routes(self) -> None:
        declined = {"authorization": {"id": "a1", "status": "declined", "decline_code": "card_blocked"}, "fees": [], "fees_total_minor": 0, "balance": {}}
        s = FakeSender([
            {"status": 201, "body": declined},
            {"status": 200, "body": {"id": "c1", "status": "stolen"}},
            {"status": 201, "body": {"refund": {"id": "r1"}}},
            {"status": 201, "body": {"id": "m1"}},
        ])
        gb = client(s)
        r = gb.card_authorizations.authorize(card_id="c1", merchant_account_id="ma1", amount_minor=500)
        self.assertEqual(r["authorization"]["decline_code"], "card_blocked")
        gb.cards.report_lost("c1", reason="stolen")
        gb.card_authorizations.refund("a1", amount_minor=100)
        gb.merchants.create(external_merchant_id="shop-1", name="Shop")
        paths = [f"{c['method']} {c['url'].split('engine.test', 1)[1]}" for c in s.calls]
        self.assertEqual(paths, ["POST /v1/card-authorizations", "POST /v1/cards/c1/report-lost",
                                 "POST /v1/card-authorizations/a1/refunds", "POST /v1/merchants"])
        self.assertIn("Idempotency-Key", s.calls[0]["headers"])
        self.assertIn("Idempotency-Key", s.calls[2]["headers"])
        self.assertEqual(json.loads(s.calls[1]["body"]), {"reason": "stolen"})
        with self.assertRaises(TypeError):
            gb.card_authorizations.authorize(card_id="c1", amount_minor=1.5)  # type: ignore[arg-type]


class SavingsTest(unittest.TestCase):
    def test_penalty_changed_and_routes(self) -> None:
        s = FakeSender([
            {"status": 200, "body": {"account_id": "s1", "accrued_interest_minor": 5}},
            {"status": 201, "body": {"fixed_deposit": {"id": "f1"}}},
            err(409, "penalty_changed", quote={}),
        ])
        gb = client(s)
        self.assertEqual(gb.accounts.interest("s1")["accrued_interest_minor"], 5)
        gb.fixed_deposits.open(source_account_id="a1", product_id="p1", term_days=30, amount_minor=1000)
        with self.assertRaises(PenaltyChangedError) as c:
            gb.fixed_deposits.break_("f1", max_penalty_minor=1)
        self.assertIsInstance(c.exception, ConflictError)
        self.assertEqual([f"{x['method']} {x['url'].split('engine.test', 1)[1]}" for x in s.calls],
                         ["GET /v1/accounts/s1/interest", "POST /v1/fixed-deposits", "POST /v1/fixed-deposits/f1/break"])
        self.assertIn("Idempotency-Key", s.calls[1]["headers"])
