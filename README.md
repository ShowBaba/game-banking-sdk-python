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

## Setup and CI

```python
from gamebanking import GameBankManagement

mgmt = GameBankManagement(os.environ["GBE_DEV_CREDENTIAL"], base_url)
game = mgmt.games.create(name="Lagos Hustle")
key = mgmt.api_keys.issue(game["id"], environment="sandbox", scopes=["account:read", "account:write", "transfer:create"])
print(key["secret"])  # shown once
mgmt.game(game["id"], "sandbox").banks.create(name="Eko Trust Bank", base_currency="NGN")
```

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
