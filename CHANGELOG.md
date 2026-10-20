# Changelog

## Unreleased

- **No base URL needed.** Clients talk to the hosted engine at `https://api.gamebank.dev` by default (`gamebanking.DEFAULT_BASE_URL`). `base_url` and `GBE_BASE_URL` still override it, for a local or self-hosted engine. The `missing_base_url` error is gone. Clients expose `base_url`.
- **Card payments charge at once by default.** `card_authorizations.authorize` now captures an approved payment in the same call (the engine's new default); the result then also carries `transaction`, `merchant_balance` and `total_debit_minor`. Pass `capture=False` to hold the payment for a later `capture` or `release` as before.

## 0.5.3

- README and PyPI metadata use **game-banking-sdk** as the package name (not `gamebanking`).

## 0.5.2

- README: PyPI vs import names, correct install pin for this release.

## 0.5.1

- Documentation: PyPI install is `game-banking-sdk` (import remains `gamebanking`).

## 0.5.0

- **Savings products.** `deposit_products` (per bank) creates, lists, gets, updates and quotes savings and fixed-deposit products. Savings products set tiered rates (whole-balance or banded), day count, accrual basis, monthly or quarterly payout, withholding tax, minimum and maximum balances, and a monthly withdrawal allowance whose excess is blocked, forfeits interest or is charged a fee. Fixed-deposit products set terms, minimum deposit, early-break forfeit and penalty, and the default maturity instruction.
- **Savings accounts.** `accounts.open` takes a product ID (and optionally an interest account ID); `accounts.interest` returns the rate, accrued interest, next payout day and recent payouts. Accounts carry `product_id` and `interest_account_id`.
- **Fixed deposits.** `fixed_deposits` opens (idempotent money call), lists, gets, changes the maturity instruction, quotes an early break (`break_quote`) and breaks. The new `PenaltyChangedError` (a conflict) is raised when the penalty rose above `max_penalty_minor`.
- Bank books add interest expense, accrued unpaid interest and money in fixed deposits. New scope `deposits:write`, fee event `savings_excess_withdrawal`, and savings and fixed-deposit webhook event types.

## 0.4.0

- **Merchants.** `merchants` creates (idempotent on `external_merchant_id`), lists, gets and updates merchants: NPC shops or player-run stores. `accounts.open` takes a merchant ID to open a merchant account, which receives card payments; accounts carry `merchant_id`.
- **Card programs.** `card_programs` (per bank) sets the BIN, validity, authorisation expiry and default limits.
- **Cards.** `cards` issues cards on player accounts (the card number and CVV are returned once; any `card_issuance` fee is charged), lists, gets and updates them, and blocks, unblocks, reports lost or stolen (`report_lost`; final, no replacement) and closes them.
- **Card payments.** `card_authorizations` authorises (by card ID or number, expiry and CVV), captures (in full or in part), releases and refunds (in parts). A decline is a result with a `decline_code`, not an exception; decline codes are exported.
- New scopes `merchants:write`, `cards:read`, `cards:write` and `cards:charge`; fee events `card_issuance` and `card_payment`; card webhook event types.

## 0.3.0

- **Webhooks: debit and credit alerts.** `verify_webhook(raw_body, signature_header, secret)` checks a delivery's `GBE-Signature` (HMAC-SHA256 over `"<t>.<raw body>"`, any `v1`, constant-time compare, 5-minute tolerance, several secrets accepted during a rotation) and returns the event; failures raise `WebhookVerificationError` with a `reason`.
- `gb.webhooks.endpoints`: create (returns the signing secret once), list, get, update (pause or re-enable), delete, rotate secret, send a test event.
- `gb.webhooks.events`: the event log and polling feed (list with an auto-paging iterator, filter by type and account), get, deliveries, redeliver.
- Typed `account.debited` / `account.credited` alert data: principal, fee and levy `charges`, total, balance after, masked counterparty, `sequence`.
- New scopes `webhooks:read` and `webhooks:write`.

## 0.2.0

- **Fees and charges.** `fees.list/get/create/update` manage a bank's fee and levy rules (each reports its `state` on the game clock; `start_now` starts one immediately). `fees.quote` returns what a payment costs now.
- **`max_fee_minor`** on transfers, hold placement and capture: the engine refuses with the new `FeeChangedError` (a `ConflictError`, code `fee_changed`) instead of charging more than the player was quoted.
- Transfer and capture results carry `fees`, `fees_total_minor` and `total_debit_minor`; holds carry `reserved_fee_minor`; ledger entries and history lines carry `kind` (`principal`, `fee`, `levy`).
- **`banks.books`** returns the bank's fee income and levies held.
- **Games:** `games.update` now renames a game and changes its slug as well as its status; `games.delete` deletes a game and revokes its keys.

## 0.1.0

- First release: players, accounts, funding, transfers, holds, reversals, history, name enquiry, banks, limits, currencies, the game clock, and management (games, API keys, developer credentials).
