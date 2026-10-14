# Changelog

## 0.2.0

- **Fees and charges.** `fees.list/get/create/update` manage a bank's fee and levy rules (each reports its `state` on the game clock; `start_now` starts one immediately). `fees.quote` returns what a payment costs now.
- **`max_fee_minor`** on transfers, hold placement and capture: the engine refuses with the new `FeeChangedError` (a `ConflictError`, code `fee_changed`) instead of charging more than the player was quoted.
- Transfer and capture results carry `fees`, `fees_total_minor` and `total_debit_minor`; holds carry `reserved_fee_minor`; ledger entries and history lines carry `kind` (`principal`, `fee`, `levy`).
- **`banks.books`** returns the bank's fee income and levies held.
- **Games:** `games.update` now renames a game and changes its slug as well as its status; `games.delete` deletes a game and revokes its keys.

## 0.1.0

- First release: players, accounts, funding, transfers, holds, reversals, history, name enquiry, banks, limits, currencies, the game clock, and management (games, API keys, developer credentials).
