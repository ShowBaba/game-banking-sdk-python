"""Contract test: the PRD §16.2 journey against a real engine.

Runs only when GBE_BASE_URL is set, e.g. GBE_BASE_URL=http://localhost:8080.
"""

import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request
import uuid
from typing import Any, Callable, Dict, List

from gamebanking import (
    AuthenticationError,
    ConflictError,
    FeeChangedError,
    GameBank,
    GameBankManagement,
    InsufficientFundsError,
    NotFoundError,
    PenaltyChangedError,
    PermissionDeniedError,
    ResponseInfo,
    verify_webhook,
)
from gamebanking._transport import urllib_sender

BASE_URL = os.environ.get("GBE_BASE_URL")
ALL_SCOPES = ["bank:read", "bank:write", "account:read", "account:write", "transfer:create",
              "funding:create", "transaction:reverse", "limits:write", "webhooks:read", "webhooks:write",
              "merchants:write", "cards:read", "cards:write", "cards:charge", "deposits:write"]
# Where the engine can reach this test's webhook receiver (the engine runs in Docker in CI and locally).
RECEIVER_HOST = os.environ.get("GBE_WEBHOOK_RECEIVER_HOST", "host.docker.internal")


class Receiver:
    """A local webhook receiver that keeps each raw delivery."""

    def __init__(self) -> None:
        self.got: List[Dict[str, Any]] = []
        got = self.got

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                got.append({"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                self.send_response(204)
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://{RECEIVER_HOST}:{self.server.server_address[1]}/hooks"

    def wait_for(self, pred: Callable[[Dict[str, Any]], bool]) -> Dict[str, Any]:
        for _ in range(100):
            for d in list(self.got):
                if pred(d):
                    return d
            time.sleep(0.2)
        raise AssertionError("no matching webhook delivery within 20s")

    def close(self) -> None:
        self.server.shutdown()


def uniq() -> str:
    return uuid.uuid4().hex[:10]


@unittest.skipUnless(BASE_URL, "set GBE_BASE_URL to run against an engine")
class ContractTest(unittest.TestCase):
    def test_prd_journey(self) -> None:
        # Sign up (a browser flow, so a plain request) to get a developer session token.
        body = json.dumps({"name": "SDK Contract PY", "email": f"sdk-py-{uniq()}@studio.test",
                           "password": "contract-test-password"}).encode()
        req = urllib.request.Request(f"{BASE_URL}/v1/auth/register", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as res:
            session = json.load(res)["session"]["token"]

        mgmt = GameBankManagement(session, BASE_URL)
        self.assertEqual(mgmt.me()["name"], "SDK Contract PY")
        game = mgmt.games.create(name=f"PY Game {uniq()}")
        key = mgmt.api_keys.issue(game["id"], environment="sandbox", label="contract", scopes=ALL_SCOPES)
        self.assertTrue(key["secret"].startswith("gbe_test_sk_"))
        bank = mgmt.game(game["id"], "sandbox").banks.create(name="Eko Trust Bank", base_currency="NGN")
        self.assertEqual(len(bank["system_accounts"]), 8)  # incl. levies_payable
        read_only = mgmt.api_keys.issue(game["id"], environment="sandbox", scopes=["account:read"])

        seen: List[ResponseInfo] = []
        gb = GameBank(key["secret"], BASE_URL, on_response=seen.append)
        self.assertEqual(gb.environment, "sandbox")

        ada = gb.players.upsert(external_player_id=f"ada-{uniq()}", display_name="Ada Obi")
        self.assertEqual(gb.players.upsert(external_player_id=ada["external_player_id"])["id"], ada["id"])
        tunde = gb.players.upsert(external_player_id=f"tunde-{uniq()}", display_name="Tunde Bello")
        ada_acct = gb.accounts.open(bank_id=bank["id"], player_id=ada["id"])
        tunde_acct = gb.accounts.open(bank_id=bank["id"], player_id=tunde["id"])

        ref = f"pay-{uniq()}"
        funded = gb.funding.create(account_id=ada_acct["id"], amount_minor=10_000_00, reason="salary",
                                   reference=ref, idempotency_key=f"fund-{ref}")
        self.assertEqual(funded["balance"]["posted_balance"], 10_000_00)
        replay = gb.funding.create(account_id=ada_acct["id"], amount_minor=10_000_00, reason="salary",
                                   reference=ref, idempotency_key=f"fund-{ref}")
        self.assertEqual(replay["transaction"]["id"], funded["transaction"]["id"])
        self.assertTrue(seen[-1].replayed)
        with self.assertRaises(ConflictError) as c:
            gb.funding.create(account_id=ada_acct["id"], amount_minor=1, reason="salary", reference=ref,
                              idempotency_key=f"fund-{ref}")
        self.assertEqual(c.exception.code, "idempotency_key_reused")

        self.assertEqual(gb.name_enquiry(bank["bank_code"], tunde_acct["account_number"])["account_name"], "Tunde Bello")
        t = gb.transfers.create(source_account_id=ada_acct["id"], destination_account_number=tunde_acct["account_number"],
                                amount_minor=2_500_00, narration="Generator")
        self.assertEqual(t["source_balance"]["posted_balance"], 7_500_00)
        self.assertEqual(t["destination_balance"]["posted_balance"], 2_500_00)

        with self.assertRaises(InsufficientFundsError) as c:
            gb.transfers.create(source_account_id=tunde_acct["id"], destination_account_id=ada_acct["id"], amount_minor=99_999_00)
        self.assertEqual(c.exception.details["available_balance"], 2_500_00)
        self.assertTrue(c.exception.request_id)
        with self.assertRaises(NotFoundError):
            gb.accounts.get("00000000-0000-0000-0000-000000000000")
        with self.assertRaises(PermissionDeniedError) as c:
            GameBank(read_only["secret"], BASE_URL).transfers.create(
                source_account_id=ada_acct["id"], destination_account_id=tunde_acct["id"], amount_minor=1)
        self.assertEqual(c.exception.code, "insufficient_scope")

        held = gb.holds.place(account_id=ada_acct["id"], amount_minor=3_000_00, reason="Order #1",
                              destination_account_id=tunde_acct["id"])
        self.assertEqual(held["balance"]["posted_balance"], 7_500_00)
        self.assertEqual(held["balance"]["available_balance"], 4_500_00)
        self.assertEqual(held["hold"]["reserved_fee_minor"], 0)
        cap = gb.holds.capture(held["hold"]["id"], amount_minor=2_000_00)
        self.assertEqual(cap["hold"]["status"], "captured")
        self.assertEqual(cap["source_balance"]["available_balance"], 5_500_00)

        # A transfer whose first response is lost must post exactly once.
        dropped = []

        def lossy(method, url, headers, data, timeout):  # type: ignore[no-untyped-def]
            res = urllib_sender(method, url, headers, data, timeout)
            if not dropped and url.endswith("/v1/transfers"):
                dropped.append(True)
                raise ConnectionResetError("connection reset after the engine processed the request")
            return res

        lost = GameBank(key["secret"], BASE_URL, sender=lossy).transfers.create(
            source_account_id=ada_acct["id"], destination_account_id=tunde_acct["id"], amount_minor=500_00)
        self.assertTrue(dropped)
        self.assertEqual(lost["source_balance"]["posted_balance"], 5_000_00)
        self.assertEqual(gb.accounts.balance(ada_acct["id"])["posted_balance"], 5_000_00)

        lines = list(gb.accounts.iter_transactions(ada_acct["id"], limit=2))
        self.assertEqual([x["amount_minor"] for x in lines], [500_00, 2_000_00, 2_500_00, 10_000_00])

        rev = gb.transactions.reverse(t["transaction"]["id"], reason="customer dispute")
        self.assertEqual(rev["type"], "reversal")
        self.assertEqual(gb.transactions.get(t["transaction"]["id"])["status"], "reversed")

        # Fees: a ₦50 + 1% transfer fee (max ₦500) via the developer credential, a levy via the game key.
        cfg = mgmt.game(game["id"], "sandbox")
        fee = cfg.fees.create(bank["id"], code="transfer_fee", name="Transfer fee", event="transfer", model="combined",
                              fixed_minor=50_00, percentage_bps=100, max_fee_minor=500_00)
        self.assertEqual(fee["state"], "in_effect")
        self.assertEqual(fee["credit_account"], "fee_income")
        levy = gb.fees.create(bank["id"], code="stamp_duty", name="Stamp duty", event="transfer", kind="levy",
                              model="fixed", fixed_minor=50_00, min_amount_minor=10_000_00)
        self.assertEqual(levy["credit_account"], "levies_payable")
        self.assertEqual(len(gb.fees.list(bank["id"])), 2)

        quote = gb.fees.quote(bank_id=bank["id"], amount_minor=1_000_00)
        self.assertEqual(quote["fees_total_minor"], 60_00)
        before = gb.accounts.balance(ada_acct["id"])["posted_balance"]
        pay = dict(source_account_id=ada_acct["id"], destination_account_id=tunde_acct["id"], amount_minor=1_000_00,
                   max_fee_minor=quote["fees_total_minor"])
        paid = gb.transfers.create(**pay)
        self.assertEqual(paid["fees_total_minor"], 60_00)
        self.assertEqual(paid["total_debit_minor"], 1_060_00)
        self.assertEqual(paid["source_balance"]["posted_balance"], before - 1_060_00)
        self.assertEqual(sorted(e["kind"] for e in paid["transaction"]["entries"]), ["fee", "fee", "principal", "principal"])
        latest = gb.accounts.transactions(ada_acct["id"], limit=2)["data"]
        self.assertTrue(any(x["kind"] == "fee" and x["narration"] == "Transfer fee" for x in latest))

        cfg.fees.update(bank["id"], fee["id"], fixed_minor=60_00)
        with self.assertRaises(FeeChangedError) as c:
            gb.transfers.create(**pay)
        self.assertIsInstance(c.exception, ConflictError)
        self.assertEqual(c.exception.code, "fee_changed")

        self.assertEqual(gb.banks.books(bank["id"])["fee_income_minor"], 60_00)
        gb.transactions.reverse(paid["transaction"]["id"], reason="refund")
        self.assertEqual(gb.banks.books(bank["id"])["fee_income_minor"], 0)
        self.assertEqual(cfg.fees.update(bank["id"], fee["id"], status="inactive")["state"], "inactive")

        # Webhooks: a debit alert reaches a real endpoint, signed, and verifies with the SDK helper.
        self.assertEqual(mgmt.game(game["id"], "sandbox").webhooks.endpoints.list(), [])
        reader = mgmt.api_keys.issue(game["id"], environment="sandbox", scopes=["account:read"])
        with self.assertRaises(PermissionDeniedError):
            GameBank(reader["secret"], BASE_URL).webhooks.endpoints.list()
        receiver = Receiver()
        try:
            ep = gb.webhooks.endpoints.create(url=receiver.url, event_types=["account.debited"], description="contract")
            self.assertTrue(ep["secret"].startswith(ep["secret_prefix"]))
            self.assertNotIn("secret", gb.webhooks.endpoints.get(ep["id"]))
            probe = gb.webhooks.endpoints.test(ep["id"])
            self.assertEqual(probe["state"], "delivered", probe["last_error"])

            sent = gb.transfers.create(source_account_id=ada_acct["id"], destination_account_id=tunde_acct["id"],
                                       amount_minor=5_00, narration="Webhook check")
            hit = receiver.wait_for(lambda d: sent["transaction"]["id"].encode() in d["body"])
            event = verify_webhook(hit["body"], hit["headers"]["gbe-signature"], ep["secret"])
            self.assertEqual(event["type"], "account.debited")
            self.assertEqual(event["data"]["account_id"], ada_acct["id"])
            self.assertEqual(event["data"]["total_minor"], 5_00)
            self.assertEqual(event["data"]["counterparty"]["account_name"], "Tunde Bello")
            self.assertEqual(event["data"]["balance_after"]["posted_minor"], sent["source_balance"]["posted_balance"])
            self.assertEqual(hit["headers"]["gbe-event-id"], event["id"])

            feed = gb.webhooks.events.list(type="account.debited", account_id=ada_acct["id"], limit=1)
            self.assertEqual(feed["data"][0]["id"], event["id"])
            self.assertEqual(gb.webhooks.events.get(event["id"])["id"], event["id"])
            self.assertEqual(gb.webhooks.events.deliveries(event["id"])[0]["state"], "delivered")
            rotated = gb.webhooks.endpoints.rotate_secret(ep["id"])
            self.assertNotEqual(rotated["secret"], ep["secret"])
            self.assertIsNotNone(rotated["previous_secret_expires_at"])
            before = len(receiver.got)
            gb.webhooks.events.redeliver(event["id"], endpoint_id=ep["id"])
            again = receiver.wait_for(lambda d: receiver.got.index(d) >= before)
            verify_webhook(again["body"], again["headers"]["gbe-signature"], rotated["secret"])
            verify_webhook(again["body"], again["headers"]["gbe-signature"], ep["secret"])  # both sign during the overlap

            self.assertEqual(gb.webhooks.endpoints.update(ep["id"], status="disabled")["status"], "disabled")
            gb.webhooks.endpoints.delete(ep["id"])
            with self.assertRaises(NotFoundError):
                gb.webhooks.endpoints.get(ep["id"])
        finally:
            receiver.close()

        # Merchants and cards: a shop with a merchant account, a card, a payment, a refund, a lost card.
        shop = gb.merchants.create(external_merchant_id=f"shop-{uniq()}", name="Mama Put", category="food")
        self.assertEqual(gb.merchants.create(external_merchant_id=shop["external_merchant_id"], name="x")["id"], shop["id"])
        till = gb.accounts.open(bank_id=bank["id"], merchant_id=shop["id"])
        self.assertEqual((till["owner_type"], till["merchant_id"]), ("merchant", shop["id"]))
        cfg.banks.update(bank["id"], feature_flags={"cards": True})
        program = cfg.card_programs.create(bank["id"], name="Classic", daily_limit_minor=3_000_00)
        self.assertEqual(len(program["bin"]), 6)
        issued = gb.cards.issue(account_id=ada_acct["id"], name_on_card="Ada Obi")
        pan = issued["card_number"]
        self.assertEqual(issued["card"]["masked_number"], pan[:6] + "******" + pan[12:])

        spendable = gb.accounts.balance(ada_acct["id"])["available_balance"]
        auth = gb.card_authorizations.authorize(card_number=pan, expiry_month=issued["card"]["expiry_month"],
                                                expiry_year=issued["card"]["expiry_year"], cvv=issued["cvv"],
                                                merchant_account_number=till["account_number"], amount_minor=200_00, capture=False)
        self.assertEqual(auth["authorization"]["status"], "approved")
        self.assertEqual(auth["balance"]["available_balance"], spendable - 200_00)
        captured = gb.card_authorizations.capture(auth["authorization"]["id"], amount_minor=150_00)
        self.assertEqual(captured["transaction"]["type"], "card_payment")
        self.assertEqual(captured["merchant_balance"]["posted_balance"], 150_00)
        self.assertEqual(captured["card_balance"]["available_balance"], spendable - 150_00)
        refunded = gb.card_authorizations.refund(auth["authorization"]["id"], amount_minor=50_00, reason="cold")
        self.assertEqual((refunded["transaction"]["type"], refunded["authorization"]["refunded_minor"]), ("card_refund", 50_00))

        instant = gb.card_authorizations.authorize(card_id=issued["card"]["id"], merchant_account_id=till["id"], amount_minor=20_00)
        self.assertEqual((instant["authorization"]["status"], instant["transaction"]["type"], instant["merchant_balance"]["posted_balance"]),
                         ("captured", "card_payment", 120_00))
        pending = gb.card_authorizations.authorize(card_id=issued["card"]["id"], merchant_account_id=till["id"], amount_minor=10_00,
                                                   capture=False)
        self.assertEqual(gb.cards.report_lost(issued["card"]["id"], reason="stolen")["status"], "stolen")
        refused = gb.card_authorizations.authorize(card_id=issued["card"]["id"], merchant_account_id=till["id"], amount_minor=10_00)
        self.assertEqual((refused["authorization"]["status"], refused["authorization"]["decline_code"]), ("declined", "card_stolen"))
        self.assertEqual(gb.card_authorizations.capture(pending["authorization"]["id"])["authorization"]["status"], "captured")
        self.assertEqual(len(gb.cards.list(account_id=ada_acct["id"])), 1)  # no replacement card
        self.assertEqual(len(gb.card_authorizations.list(card_id=issued["card"]["id"])), 4)

        gb.clock.configure(mode="manual")
        self.assertIn("game_day", gb.clock.advance(days=1)["clock"])
        recon = gb.reconcile()
        self.assertTrue(recon["ok"], recon["differences"])

        # Savings: ₦100,000 at 36.5% earns ₦100 a game day; a fixed deposit can be broken early.
        cfg.banks.update(bank["id"], feature_flags={"savings": True})
        saver = cfg.deposit_products.create(bank["id"], code="easy_saver", name="Easy Saver", kind="savings",
                                            rate_tiers=[{"from_minor": 0, "rate_bps": 3650}])
        term = cfg.deposit_products.create(bank["id"], code="term", name="Term Deposit", kind="fixed_deposit",
                                           terms=[{"days": 30, "rate_bps": 3650}], early_forfeit_bps=10_000, early_penalty_fixed_minor=100_00)
        savings = gb.accounts.open(bank_id=bank["id"], player_id=ada["id"], product_id=saver["id"])
        self.assertEqual(savings["account_type"], "savings")
        gb.funding.create(account_id=savings["id"], amount_minor=100_000_00, reason="savings", reference=f"save-{uniq()}")
        gb.funding.create(account_id=ada_acct["id"], amount_minor=100_000_00, reason="deposit", reference=f"fd-{uniq()}")
        fd = gb.fixed_deposits.open(source_account_id=ada_acct["id"], product_id=term["id"], term_days=30, amount_minor=100_000_00)
        self.assertEqual(fd["fixed_deposit"]["status"], "active")
        self.assertEqual(gb.deposit_products.quote(product_id=term["id"], amount_minor=100_000_00, term_days=30)["gross_interest_minor"], 3_000_00)
        gb.clock.advance(days=2)
        self.assertEqual(gb.accounts.interest(savings["id"])["accrued_interest_minor"], 200_00)
        bq = gb.fixed_deposits.break_quote(fd["fixed_deposit"]["id"])
        self.assertEqual(bq["payout_minor"], 100_000_00 - 100_00)
        with self.assertRaises(PenaltyChangedError):
            gb.fixed_deposits.break_(fd["fixed_deposit"]["id"], max_penalty_minor=50_00)
        self.assertEqual(gb.fixed_deposits.break_(fd["fixed_deposit"]["id"], max_penalty_minor=bq["penalty_minor"])["fixed_deposit"]["status"], "broken")

        # Renaming and deleting a game. Deleting revokes its keys at once.
        self.assertEqual(mgmt.games.update(game["id"], name="PY Game renamed")["name"], "PY Game renamed")
        mgmt.games.delete(game["id"])
        with self.assertRaises(NotFoundError):
            mgmt.games.get(game["id"])
        with self.assertRaises(AuthenticationError):
            gb.clock.get()


if __name__ == "__main__":
    unittest.main()
