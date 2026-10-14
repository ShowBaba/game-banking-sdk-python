"""Contract test: the PRD §16.2 journey against a real engine.

Runs only when GBE_BASE_URL is set, e.g. GBE_BASE_URL=http://localhost:8080.
"""

import json
import os
import unittest
import urllib.request
import uuid
from typing import List

from gamebanking import (
    AuthenticationError,
    ConflictError,
    FeeChangedError,
    GameBank,
    GameBankManagement,
    InsufficientFundsError,
    NotFoundError,
    PermissionDeniedError,
    ResponseInfo,
)
from gamebanking._transport import urllib_sender

BASE_URL = os.environ.get("GBE_BASE_URL")
ALL_SCOPES = ["bank:read", "bank:write", "account:read", "account:write", "transfer:create",
              "funding:create", "transaction:reverse", "limits:write"]


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

        gb.clock.configure(mode="manual")
        self.assertIn("game_day", gb.clock.advance(days=1)["clock"])
        recon = gb.reconcile()
        self.assertTrue(recon["ok"], recon["differences"])

        # Renaming and deleting a game. Deleting revokes its keys at once.
        self.assertEqual(mgmt.games.update(game["id"], name="PY Game renamed")["name"], "PY Game renamed")
        mgmt.games.delete(game["id"])
        with self.assertRaises(NotFoundError):
            mgmt.games.get(game["id"])
        with self.assertRaises(AuthenticationError):
            gb.clock.get()


if __name__ == "__main__":
    unittest.main()
