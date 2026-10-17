# gamebanking (Python)

Server-side SDK for the Game Banking Engine. Python 3.9+, standard library only.

> Game API keys move money. Use this SDK on your game servers only.

## Install

```bash
pip install gamebanking
```

## Quick start

```python
import os
from gamebanking import GameBank, InsufficientFundsError

gb = GameBank(os.environ["GBE_API_KEY"], "https://your-engine.example.com")

player = gb.players.upsert(external_player_id="user-42", display_name="Ada Obi")
account = gb.accounts.open(bank_id=BANK_ID, player_id=player["id"])
gb.funding.create(
    account_id=account["id"], amount_minor=500_000, reason="salary",
    reference="payroll-2040-06-01-user-42",
    idempotency_key="payroll-2040-06-01-user-42",  # your stable ID: retrying never pays twice
)

who = gb.name_enquiry("058", "5915945174")
try:
    gb.transfers.create(source_account_id=account["id"], destination_account_number="5915945174", amount_minor=1_000)
except InsufficientFundsError as e:
    print("available:", e.details["available_balance"], "request:", e.request_id)

for line in gb.accounts.iter_transactions(account["id"]):
    print(line["direction"], line["amount_display"], line["narration"])
```

Responses are plain dicts, typed with `TypedDict`s in `gamebanking.types` for editor completion. Holds: `gb.holds.place(...)`, `capture(hold_id, amount_minor=...)`, `release(hold_id)`. Reversals: `gb.transactions.reverse(txn_id, reason=...)`. Clock: `gb.clock.get()`, `configure(...)`, `advance(...)`.

## Fees and charges

```python
from gamebanking import FeeChangedError

# Show the player what the transfer costs, then cap the fee at what they saw.
quote = gb.fees.quote(bank_id=BANK_ID, amount_minor=2_000_00)
try:
    r = gb.transfers.create(source_account_id=account["id"], destination_account_number="5915945174",
                            amount_minor=2_000_00, max_fee_minor=quote["fees_total_minor"])
    print(r["fees"], r["total_debit_minor"])  # each fee is its own ledger and statement line
except FeeChangedError:
    ...  # the schedule changed: quote again

# Configure fees (bank:write): ₦50 + 1%, capped at ₦500, on transfers of ₦1,000 or more.
gb.fees.create(BANK_ID, code="transfer_fee", name="Transfer fee", event="transfer", model="combined",
               fixed_minor=50_00, percentage_bps=100, max_fee_minor=500_00, min_amount_minor=1_000_00)
books = gb.banks.books(BANK_ID)  # fee_income_minor, levies_payable_minor
```

## Merchants and cards

```python
# A shop and its merchant account (card payments settle here).
shop = gb.merchants.create(external_merchant_id="shop:mama-put", name="Mama Put", category="food")
till = gb.accounts.open(bank_id=BANK_ID, merchant_id=shop["id"])

# Once per bank: turn on cards and add a program (bank:write).
gb.banks.update(BANK_ID, feature_flags={"cards": True})
gb.card_programs.create(BANK_ID, name="Classic", daily_limit_minor=50_000_00)

# Issue a card: card_number and cvv are shown only now.
issued = gb.cards.issue(account_id=account["id"])

# Pay: an approved payment is charged at once (status "captured"). A decline is a result, not an exception.
paid = gb.card_authorizations.authorize(card_id=issued["card"]["id"], merchant_account_id=till["id"], amount_minor=2_500_00)
if paid["authorization"]["status"] == "declined":
    show_player(paid["authorization"]["decline_code"])  # e.g. "insufficient_funds"

# Or hold first when the final amount or the sale isn't settled yet (a fuel pump, a pre-order).
held = gb.card_authorizations.authorize(card_id=issued["card"]["id"], merchant_account_id=till["id"], amount_minor=2_500_00, capture=False)
gb.card_authorizations.capture(held["authorization"]["id"], amount_minor=2_100_00)  # or release(); refund() later, in parts

gb.cards.report_lost(issued["card"]["id"], reason="stolen")  # final; no replacement is issued
```

## Savings and fixed deposits

```python
# Once per bank: turn savings on and define products (bank:write).
gb.banks.update(BANK_ID, feature_flags={"savings": True})
saver = gb.deposit_products.create(BANK_ID, code="easy_saver", name="Easy Saver", kind="savings",
                                   rate_tiers=[{"from_minor": 0, "rate_bps": 300}], withholding_tax_bps=1000,
                                   withdrawals_per_month=3, excess_withdrawal_action="forfeit_interest")
term = gb.deposit_products.create(BANK_ID, code="term", name="Term Deposit", kind="fixed_deposit",
                                  terms=[{"days": 90, "rate_bps": 800}])

# A savings account earns daily on the game clock and is paid monthly.
savings = gb.accounts.open(bank_id=BANK_ID, player_id=player["id"], product_id=saver["id"])
print(gb.accounts.interest(savings["id"])["accrued_interest_minor"])

# A fixed deposit (deposits:write); break it early with a quote first.
fd = gb.fixed_deposits.open(source_account_id=account["id"], product_id=term["id"], term_days=90, amount_minor=50_000_00)["fixed_deposit"]
quote = gb.fixed_deposits.break_quote(fd["id"])
gb.fixed_deposits.break_(fd["id"], max_penalty_minor=quote["penalty_minor"])  # PenaltyChangedError if it rose
```

## Webhooks: debit and credit alerts

Every money movement on a player's account sends a signed `account.debited` or `account.credited` event to your endpoint. Verify it with the **raw** body:

```python
from gamebanking import verify_webhook, WebhookVerificationError

# Register once (webhooks:write). The secret is shown only here.
ep = gb.webhooks.endpoints.create(url="https://game.example.com/gbe/webhooks", event_types=["account.debited", "account.credited"])

@app.post("/gbe/webhooks")  # Flask
def gbe_webhook():
    try:
        event = verify_webhook(request.get_data(), request.headers.get("GBE-Signature"), os.environ["GBE_WEBHOOK_SECRET"])
    except WebhookVerificationError:
        return "", 400
    if event["type"] == "account.debited":
        a = event["data"]  # amount_minor, charges, total_minor, balance_after, counterparty, sequence…
        notify_player(a["player_id"], f"-{a['total_display']} {a['narration'] or ''}")
    return "", 204  # answer within 10s; delivery is at least once, so dedupe on event["id"]
```

`gb.webhooks.endpoints` also has `list`, `get`, `update` (`status="disabled"` / `"active"`), `delete`, `rotate_secret` (the old secret keeps signing for 24 hours) and `test`. `gb.webhooks.events` has `list` / `iter` (the last 30 days, filterable by `type` and `account_id`, also a polling feed), `get`, `deliveries` and `redeliver`.

## Setup and CI

```python
from gamebanking import GameBankManagement

mgmt = GameBankManagement(os.environ["GBE_DEV_CREDENTIAL"], base_url)
game = mgmt.games.create(name="Lagos Hustle")
key = mgmt.api_keys.issue(game["id"], environment="sandbox", scopes=["account:read", "account:write", "transfer:create"])
print(key["secret"])  # shown once
mgmt.game(game["id"], "sandbox").banks.create(name="Eko Trust Bank", base_currency="NGN")
```

`mgmt.games.update(id, name=..., slug=..., status=...)` renames or suspends a game; `mgmt.games.delete(id)` deletes it and revokes its keys.

## Behaviour

Retries, idempotency keys, error types and money helpers follow the shared contract in [`CONTRACT.md`](CONTRACT.md). The network error class is `APIConnectionError`, so it doesn't shadow Python's built-in `ConnectionError`. Client options: `timeout` (seconds), `max_retries`, `on_response`, `sender` (a custom HTTP function). `to_minor("100.50", 2)` and `format_minor(10050, 2)` convert amounts; floats are refused.

The client is synchronous. Call it from a thread pool (`asyncio.to_thread`) in async servers.

## Development

Unit tests need no network:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

The contract test runs the full journey against a real engine. `ci/docker-compose.yml` starts one (PostgreSQL plus the engine's published image) on port 8080:

```bash
docker compose -f ci/docker-compose.yml up -d && ./ci/wait-for-engine.sh
GBE_BASE_URL=http://localhost:8080 PYTHONPATH=src python3 -m unittest discover -s tests
docker compose -f ci/docker-compose.yml down -v
```

To test against a local engine build instead, build its image and set `GBE_ENGINE_IMAGE` to that tag. CI (`.github/workflows/ci.yml`) runs both on every push.
