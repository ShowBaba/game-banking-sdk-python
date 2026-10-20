"""The GameBank (runtime) and GameBankManagement (setup) clients."""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterator, List, Optional, cast
from urllib.parse import quote

from . import types as t
from ._transport import ResponseInfo, Sender, Transport


def _q(segment: str) -> str:
    return quote(segment, safe="")


def _body(**fields: Any) -> Dict[str, Any]:
    """Drops unset (None) fields so the engine applies its defaults."""
    return {k: v for k, v in fields.items() if v is not None}


def _amount(value: Any, field: str = "amount_minor") -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an int number of minor units (got {value!r})")


class _Resource:
    def __init__(self, transport: Transport) -> None:
        self._t = transport


class Players(_Resource):
    def upsert(self, *, external_player_id: str, display_name: Optional[str] = None,
               metadata: Optional[Dict[str, Any]] = None) -> t.Player:
        """Maps your player ID to an engine player; repeat calls return the same player."""
        body = _body(external_player_id=external_player_id, display_name=display_name, metadata=metadata)
        return cast(t.Player, self._t.request("POST", "/v1/players", body=body, retry_safe=True))

    def get(self, player_id: str) -> t.Player:
        return cast(t.Player, self._t.request("GET", f"/v1/players/{_q(player_id)}"))

    def find_by_external_id(self, external_player_id: str) -> t.Player:
        """Looks a player up by your own player ID."""
        return cast(t.Player, self._t.request("GET", "/v1/players", query={"external_player_id": external_player_id}))


class Accounts(_Resource):
    def open(self, *, bank_id: str, player_id: Optional[str] = None, merchant_id: Optional[str] = None,
             account_type: Optional[str] = None, account_name: Optional[str] = None, currency: Optional[str] = None,
             product_id: Optional[str] = None, interest_account_id: Optional[str] = None,
             metadata: Optional[Dict[str, Any]] = None) -> t.Account:
        """Opens a player account (``player_id``) or a merchant account (``merchant_id``), which receives card
        payments. A ``product_id`` makes it a savings account that earns interest under that product."""
        body = _body(bank_id=bank_id, player_id=player_id, merchant_id=merchant_id, account_type=account_type,
                     account_name=account_name, currency=currency, product_id=product_id,
                     interest_account_id=interest_account_id, metadata=metadata)
        return cast(t.Account, self._t.request("POST", "/v1/accounts", body=body))

    def get(self, account_id: str) -> t.Account:
        return cast(t.Account, self._t.request("GET", f"/v1/accounts/{_q(account_id)}"))

    def list(self, *, bank_id: Optional[str] = None, player_id: Optional[str] = None, merchant_id: Optional[str] = None,
             include_system: bool = False, limit: Optional[int] = None) -> List[t.Account]:
        q = {"bank_id": bank_id, "player_id": player_id, "merchant_id": merchant_id, "include_system": include_system or None, "limit": limit}
        return cast(List[t.Account], self._t.request("GET", "/v1/accounts", query=q)["data"])

    def update_status(self, account_id: str, *, status: str, reason: Optional[str] = None) -> t.Account:
        """Freezes (no debits), unfreezes ("active") or closes an account. Closing needs a zero balance."""
        return cast(t.Account, self._t.request("PATCH", f"/v1/accounts/{_q(account_id)}", body=_body(status=status, reason=reason)))

    def balance(self, account_id: str) -> t.Balance:
        return cast(t.Balance, self._t.request("GET", f"/v1/accounts/{_q(account_id)}/balance"))

    def transactions(self, account_id: str, *, limit: Optional[int] = None, cursor: Optional[str] = None) -> t.HistoryPage:
        """One page of history, newest first. Pass ``next_cursor`` back as ``cursor`` for the next page."""
        return cast(t.HistoryPage, self._t.request("GET", f"/v1/accounts/{_q(account_id)}/transactions",
                                                   query={"limit": limit, "cursor": cursor}))

    def iter_transactions(self, account_id: str, *, limit: Optional[int] = None) -> Iterator[t.HistoryItem]:
        """Every history line, newest first, fetching pages as needed."""
        cursor: Optional[str] = None
        while True:
            page = self.transactions(account_id, limit=limit, cursor=cursor)
            yield from page["data"]
            cursor = page.get("next_cursor")
            if not cursor:
                return

    def interest(self, account_id: str) -> t.AccountInterest:
        """A savings or fixed-deposit account's rate, accrued interest, next payout and recent payouts."""
        return cast(t.AccountInterest, self._t.request("GET", f"/v1/accounts/{_q(account_id)}/interest"))

    def holds(self, account_id: str, *, status: Optional[str] = None) -> List[t.Hold]:
        return cast(List[t.Hold], self._t.request("GET", f"/v1/accounts/{_q(account_id)}/holds", query={"status": status})["data"])


class Funding(_Resource):
    def create(self, *, account_id: str, amount_minor: int, reason: str, reference: str,
               currency: Optional[str] = None, source_account_id: Optional[str] = None,
               narration: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None,
               idempotency_key: Optional[str] = None) -> t.FundingResult:
        """Credits a player account from the bank's issuance account. Needs the funding:create scope."""
        _amount(amount_minor)
        body = _body(account_id=account_id, amount_minor=amount_minor, reason=reason, reference=reference,
                     currency=currency, source_account_id=source_account_id, narration=narration, metadata=metadata)
        return cast(t.FundingResult, self._t.request("POST", "/v1/funding", body=body, idempotent=True, idempotency_key=idempotency_key))


class Transfers(_Resource):
    def create(self, *, source_account_id: str, amount_minor: int,
               destination_account_id: Optional[str] = None, destination_account_number: Optional[str] = None,
               destination_bank_code: Optional[str] = None, bank_id: Optional[str] = None,
               currency: Optional[str] = None, reference: Optional[str] = None, narration: Optional[str] = None,
               metadata: Optional[Dict[str, Any]] = None, max_fee_minor: Optional[int] = None,
               idempotency_key: Optional[str] = None) -> t.TransferResult:
        """Moves money between two customer accounts in the same bank, atomically.

        Fees are charged to the sender on top of the amount. Pass ``max_fee_minor``
        (e.g. a quote's ``fees_total_minor``) to get ``FeeChangedError`` rather than
        a higher fee if the schedule changed since the player saw the quote.
        """
        _amount(amount_minor)
        body = _body(source_account_id=source_account_id, amount_minor=amount_minor,
                     destination_account_id=destination_account_id, destination_account_number=destination_account_number,
                     destination_bank_code=destination_bank_code, bank_id=bank_id, currency=currency,
                     reference=reference, narration=narration, metadata=metadata, max_fee_minor=max_fee_minor)
        return cast(t.TransferResult, self._t.request("POST", "/v1/transfers", body=body, idempotent=True, idempotency_key=idempotency_key))


class Holds(_Resource):
    def place(self, *, account_id: str, amount_minor: int, reason: str, reference: Optional[str] = None,
              destination_account_id: Optional[str] = None, destination_account_number: Optional[str] = None,
              expires_at_game: Optional[str] = None, expires_in_game_seconds: Optional[int] = None,
              max_fee_minor: Optional[int] = None, idempotency_key: Optional[str] = None) -> t.HoldResult:
        """Reserves funds: available balance drops, posted balance does not. The hold also
        reserves the fees its capture is expected to cost (``reserved_fee_minor``)."""
        _amount(amount_minor)
        body = _body(account_id=account_id, amount_minor=amount_minor, reason=reason, reference=reference,
                     destination_account_id=destination_account_id, destination_account_number=destination_account_number,
                     expires_at_game=expires_at_game, expires_in_game_seconds=expires_in_game_seconds,
                     max_fee_minor=max_fee_minor)
        return cast(t.HoldResult, self._t.request("POST", "/v1/holds", body=body, idempotent=True, idempotency_key=idempotency_key))

    def get(self, hold_id: str) -> t.Hold:
        return cast(t.Hold, self._t.request("GET", f"/v1/holds/{_q(hold_id)}"))

    def capture(self, hold_id: str, *, amount_minor: Optional[int] = None, destination_account_id: Optional[str] = None,
                destination_account_number: Optional[str] = None, narration: Optional[str] = None,
                reference: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None,
                max_fee_minor: Optional[int] = None, idempotency_key: Optional[str] = None) -> t.CaptureResult:
        """Posts all (``amount_minor=None``) or part of a hold as a transfer, with its fees, and releases the rest."""
        if amount_minor is not None:
            _amount(amount_minor)
        body = _body(amount_minor=amount_minor, destination_account_id=destination_account_id,
                     destination_account_number=destination_account_number, narration=narration,
                     reference=reference, metadata=metadata, max_fee_minor=max_fee_minor)
        return cast(t.CaptureResult, self._t.request("POST", f"/v1/holds/{_q(hold_id)}/capture", body=body,
                                                     idempotent=True, idempotency_key=idempotency_key))

    def release(self, hold_id: str, *, reason: Optional[str] = None, idempotency_key: Optional[str] = None) -> t.HoldResult:
        """Cancels a hold and restores the available balance."""
        return cast(t.HoldResult, self._t.request("POST", f"/v1/holds/{_q(hold_id)}/release", body=_body(reason=reason),
                                                  idempotent=True, idempotency_key=idempotency_key))


class Transactions(_Resource):
    def get(self, transaction_id: str) -> t.Transaction:
        return cast(t.Transaction, self._t.request("GET", f"/v1/transactions/{_q(transaction_id)}"))

    def reverse(self, transaction_id: str, *, reason: str, narration: Optional[str] = None,
                idempotency_key: Optional[str] = None) -> t.Transaction:
        """Posts a compensating transaction. Needs the transaction:reverse scope."""
        return cast(t.Transaction, self._t.request("POST", f"/v1/transactions/{_q(transaction_id)}/reverse",
                                                   body=_body(reason=reason, narration=narration),
                                                   idempotent=True, idempotency_key=idempotency_key))


class Banks(_Resource):
    def create(self, *, name: str, base_currency: str, slug: Optional[str] = None, bank_code: Optional[str] = None,
               branding: Optional[Dict[str, Any]] = None, feature_flags: Optional[Dict[str, bool]] = None) -> t.Bank:
        """Creates a bank with its own system ledger accounts."""
        body = _body(name=name, base_currency=base_currency, slug=slug, bank_code=bank_code,
                     branding=branding, feature_flags=feature_flags)
        return cast(t.Bank, self._t.request("POST", "/v1/banks", body=body))

    def list(self) -> List[t.Bank]:
        return cast(List[t.Bank], self._t.request("GET", "/v1/banks")["data"])

    def get(self, bank_id: str) -> t.Bank:
        return cast(t.Bank, self._t.request("GET", f"/v1/banks/{_q(bank_id)}"))

    def update(self, bank_id: str, *, name: Optional[str] = None, branding: Optional[Dict[str, Any]] = None,
               feature_flags: Optional[Dict[str, bool]] = None, status: Optional[str] = None) -> t.Bank:
        body = _body(name=name, branding=branding, feature_flags=feature_flags, status=status)
        return cast(t.Bank, self._t.request("PATCH", f"/v1/banks/{_q(bank_id)}", body=body))

    def limits(self, bank_id: str) -> t.Limits:
        return cast(t.Limits, self._t.request("GET", f"/v1/banks/{_q(bank_id)}/limits"))

    def books(self, bank_id: str) -> t.BankBooks:
        """The bank's own ledger accounts: fee income earned and levies held."""
        return cast(t.BankBooks, self._t.request("GET", f"/v1/banks/{_q(bank_id)}/books"))

    def set_limits(self, bank_id: str, limits: Dict[str, Optional[Dict[str, Optional[int]]]]) -> t.Limits:
        """Sets caps per scope, e.g. ``{"player_funding": {"daily_max": 500000}}``; ``None`` removes a scope's limits."""
        return cast(t.Limits, self._t.request("PUT", f"/v1/banks/{_q(bank_id)}/limits", body=limits))


class Fees(_Resource):
    """A bank's fees and levies, and fee quotes."""

    def list(self, bank_id: str) -> List[t.FeeRule]:
        """Active and inactive rules, each with its current ``state``."""
        return cast(List[t.FeeRule], self._t.request("GET", f"/v1/banks/{_q(bank_id)}/fees")["data"])

    def get(self, bank_id: str, fee_id: str) -> t.FeeRule:
        return cast(t.FeeRule, self._t.request("GET", f"/v1/banks/{_q(bank_id)}/fees/{_q(fee_id)}"))

    def create(self, bank_id: str, *, code: str, name: str, event: str, model: str, kind: Optional[str] = None,
               fixed_minor: Optional[int] = None, percentage_bps: Optional[int] = None,
               min_fee_minor: Optional[int] = None, max_fee_minor: Optional[int] = None,
               min_amount_minor: Optional[int] = None, max_amount_minor: Optional[int] = None,
               status: Optional[str] = None, effective_from: Optional[str] = None, effective_to: Optional[str] = None,
               start_now: Optional[bool] = None) -> t.FeeRule:
        """Adds a fee or levy. ``event``: transfer, hold_capture or account_maintenance; ``model``: fixed,
        percentage or combined; ``kind``: fee (default) or levy. Times are game time. Needs bank:write."""
        body = _body(code=code, name=name, event=event, model=model, kind=kind, fixed_minor=fixed_minor,
                     percentage_bps=percentage_bps, min_fee_minor=min_fee_minor, max_fee_minor=max_fee_minor,
                     min_amount_minor=min_amount_minor, max_amount_minor=max_amount_minor, status=status,
                     effective_from=effective_from, effective_to=effective_to, start_now=start_now)
        return cast(t.FeeRule, self._t.request("POST", f"/v1/banks/{_q(bank_id)}/fees", body=body))

    def update(self, bank_id: str, fee_id: str, *, name: Optional[str] = None, kind: Optional[str] = None,
               model: Optional[str] = None, fixed_minor: Optional[int] = None, percentage_bps: Optional[int] = None,
               min_fee_minor: Optional[int] = None, max_fee_minor: Optional[int] = None,
               min_amount_minor: Optional[int] = None, max_amount_minor: Optional[int] = None,
               status: Optional[str] = None, effective_from: Optional[str] = None, effective_to: Optional[str] = None,
               start_now: Optional[bool] = None, clear: Optional[List[str]] = None) -> t.FeeRule:
        """Changes, pauses (``status="inactive"``) or resumes a fee; bumps its version. ``clear`` resets
        fields to "no limit", e.g. ``["max_fee_minor"]``. code and event cannot change."""
        body = _body(name=name, kind=kind, model=model, fixed_minor=fixed_minor, percentage_bps=percentage_bps,
                     min_fee_minor=min_fee_minor, max_fee_minor=max_fee_minor, min_amount_minor=min_amount_minor,
                     max_amount_minor=max_amount_minor, status=status, effective_from=effective_from,
                     effective_to=effective_to, start_now=start_now, clear=clear)
        return cast(t.FeeRule, self._t.request("PATCH", f"/v1/banks/{_q(bank_id)}/fees/{_q(fee_id)}", body=body))

    def quote(self, *, bank_id: str, amount_minor: int, event: str = "transfer") -> t.FeeQuote:
        """What a transfer (or ``event="hold_capture"``) would cost now. Show it to the player, then
        pass ``fees_total_minor`` as ``max_fee_minor`` on the payment."""
        _amount(amount_minor)
        return cast(t.FeeQuote, self._t.request("POST", "/v1/fees/quote",
                                                body={"bank_id": bank_id, "event": event, "amount_minor": amount_minor}))


class Currencies(_Resource):
    def list(self) -> List[t.Currency]:
        """Standard ISO currencies plus this game's custom units."""
        return cast(List[t.Currency], self._t.request("GET", "/v1/currencies")["data"])

    def create(self, *, code: str, name: str, exponent: int, symbol: Optional[str] = None) -> t.Currency:
        """Defines a custom virtual unit, e.g. ``create(code="GOLD", name="Gold", exponent=0)``."""
        return cast(t.Currency, self._t.request("POST", "/v1/currencies", body=_body(code=code, name=name, exponent=exponent, symbol=symbol)))


class GameClock(_Resource):
    def get(self) -> t.Clock:
        return cast(t.Clock, self._t.request("GET", "/v1/clock"))

    def configure(self, *, mode: Optional[str] = None, speed: Optional[int] = None,
                  time_zone: Optional[str] = None, game_time: Optional[str] = None) -> t.Clock:
        """Changes mode, speed or time zone, or jumps forward. Needs limits:write."""
        body = _body(mode=mode, speed=speed, time_zone=time_zone, game_time=game_time)
        return cast(t.Clock, self._t.request("PUT", "/v1/clock", body=body))

    def advance(self, *, seconds: Optional[int] = None, minutes: Optional[int] = None, hours: Optional[int] = None,
                days: Optional[int] = None, to: Optional[str] = None) -> t.AdvanceClockResult:
        """Moves a manual clock forward and runs the jobs that became due."""
        body = _body(seconds=seconds, minutes=minutes, hours=hours, days=days, to=to)
        return cast(t.AdvanceClockResult, self._t.request("POST", "/v1/clock/advance", body=body))


class DepositProducts(_Resource):
    def list(self, bank_id: str) -> List[t.DepositProduct]:
        return cast(List[t.DepositProduct], self._t.request("GET", f"/v1/banks/{_q(bank_id)}/deposit-products")["data"])

    def get(self, bank_id: str, product_id: str) -> t.DepositProduct:
        return cast(t.DepositProduct, self._t.request("GET", f"/v1/banks/{_q(bank_id)}/deposit-products/{_q(product_id)}"))

    def create(self, bank_id: str, *, code: str, name: str, kind: str, **settings: Any) -> t.DepositProduct:
        """Adds a savings product (``rate_tiers=[{"from_minor": 0, "rate_bps": 300}]``) or a fixed-deposit
        product (``terms=[{"days": 90, "rate_bps": 800}]``). Other settings: tier_method, day_count,
        accrual_basis, payout_frequency, withholding_tax_bps, min_opening_minor, min_balance_minor,
        max_balance_minor, withdrawals_per_month, excess_withdrawal_action, early_forfeit_bps,
        early_penalty_fixed_minor, early_penalty_bps, default_maturity_instruction, status. Needs bank:write."""
        body = _body(code=code, name=name, kind=kind, **settings)
        return cast(t.DepositProduct, self._t.request("POST", f"/v1/banks/{_q(bank_id)}/deposit-products", body=body))

    def update(self, bank_id: str, product_id: str, **settings: Any) -> t.DepositProduct:
        """Changes a product (bumps its version); code and kind can't change. ``clear`` resets
        max_balance_minor or withdrawals_per_month to none."""
        return cast(t.DepositProduct, self._t.request("PATCH", f"/v1/banks/{_q(bank_id)}/deposit-products/{_q(product_id)}",
                                                      body=_body(**settings)))

    def quote(self, *, product_id: str, amount_minor: int, days: Optional[int] = None,
              term_days: Optional[int] = None) -> t.DepositQuote:
        """Projects the interest an amount would earn over ``days`` (savings) or a ``term_days`` term."""
        _amount(amount_minor)
        body = _body(product_id=product_id, amount_minor=amount_minor, days=days, term_days=term_days)
        return cast(t.DepositQuote, self._t.request("POST", "/v1/deposit-products/quote", body=body))


class FixedDeposits(_Resource):
    def open(self, *, source_account_id: str, product_id: str, term_days: int, amount_minor: int,
             maturity_instruction: Optional[str] = None, payout_account_id: Optional[str] = None,
             idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Books a fixed deposit at the term's current rate. ``maturity_instruction``: payout,
        rollover_principal or rollover_all. Needs deposits:write."""
        _amount(amount_minor)
        body = _body(source_account_id=source_account_id, product_id=product_id, term_days=term_days, amount_minor=amount_minor,
                     maturity_instruction=maturity_instruction, payout_account_id=payout_account_id)
        return cast(Dict[str, Any], self._t.request("POST", "/v1/fixed-deposits", body=body, idempotent=True, idempotency_key=idempotency_key))

    def list(self, *, player_id: Optional[str] = None, source_account_id: Optional[str] = None,
             status: Optional[str] = None, limit: Optional[int] = None) -> List[t.FixedDeposit]:
        q = {"player_id": player_id, "source_account_id": source_account_id, "status": status, "limit": limit}
        return cast(List[t.FixedDeposit], self._t.request("GET", "/v1/fixed-deposits", query=q)["data"])

    def get(self, deposit_id: str) -> t.FixedDeposit:
        return cast(t.FixedDeposit, self._t.request("GET", f"/v1/fixed-deposits/{_q(deposit_id)}"))

    def update(self, deposit_id: str, *, maturity_instruction: str) -> t.FixedDeposit:
        """Changes what happens at maturity."""
        return cast(t.FixedDeposit, self._t.request("PATCH", f"/v1/fixed-deposits/{_q(deposit_id)}",
                                                    body={"maturity_instruction": maturity_instruction}))

    def break_quote(self, deposit_id: str) -> t.BreakQuote:
        """What breaking the deposit early pays now."""
        return cast(t.BreakQuote, self._t.request("GET", f"/v1/fixed-deposits/{_q(deposit_id)}/break-quote"))

    def break_(self, deposit_id: str, *, max_penalty_minor: Optional[int] = None,
               idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Breaks the deposit early. Pass the quote's ``penalty_minor`` as ``max_penalty_minor``
        (PenaltyChangedError if it rose). Named ``break_`` because ``break`` is a keyword."""
        return cast(Dict[str, Any], self._t.request("POST", f"/v1/fixed-deposits/{_q(deposit_id)}/break",
                                                    body=_body(max_penalty_minor=max_penalty_minor),
                                                    idempotent=True, idempotency_key=idempotency_key))


class Merchants(_Resource):
    def create(self, *, external_merchant_id: str, name: str, category: Optional[str] = None,
               owner_player_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> t.Merchant:
        """Registers a merchant (an NPC shop or a player-run store). Repeat calls with the same
        ``external_merchant_id`` return it. Needs merchants:write."""
        body = _body(external_merchant_id=external_merchant_id, name=name, category=category,
                     owner_player_id=owner_player_id, metadata=metadata)
        return cast(t.Merchant, self._t.request("POST", "/v1/merchants", body=body, retry_safe=True))

    def list(self, *, status: Optional[str] = None, owner_player_id: Optional[str] = None,
             external_merchant_id: Optional[str] = None, limit: Optional[int] = None) -> List[t.Merchant]:
        q = {"status": status, "owner_player_id": owner_player_id, "external_merchant_id": external_merchant_id, "limit": limit}
        return cast(List[t.Merchant], self._t.request("GET", "/v1/merchants", query=q)["data"])

    def get(self, merchant_id: str) -> t.Merchant:
        return cast(t.Merchant, self._t.request("GET", f"/v1/merchants/{_q(merchant_id)}"))

    def update(self, merchant_id: str, *, name: Optional[str] = None, category: Optional[str] = None,
               status: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> t.Merchant:
        """Renames, recategorises, suspends (card payments are then declined) or reactivates a merchant."""
        body = _body(name=name, category=category, status=status, metadata=metadata)
        return cast(t.Merchant, self._t.request("PATCH", f"/v1/merchants/{_q(merchant_id)}", body=body))


class CardPrograms(_Resource):
    def list(self, bank_id: str) -> List[t.CardProgram]:
        return cast(List[t.CardProgram], self._t.request("GET", f"/v1/banks/{_q(bank_id)}/card-programs")["data"])

    def get(self, bank_id: str, program_id: str) -> t.CardProgram:
        return cast(t.CardProgram, self._t.request("GET", f"/v1/banks/{_q(bank_id)}/card-programs/{_q(program_id)}"))

    def create(self, bank_id: str, *, name: str, bin: Optional[str] = None, validity_months: Optional[int] = None,
               auth_expiry_seconds: Optional[int] = None, per_txn_limit_minor: Optional[int] = None,
               daily_limit_minor: Optional[int] = None, status: Optional[str] = None) -> t.CardProgram:
        """Adds a card program. Turn on the bank's ``cards`` feature flag to issue cards. Needs bank:write."""
        body = _body(name=name, bin=bin, validity_months=validity_months, auth_expiry_seconds=auth_expiry_seconds,
                     per_txn_limit_minor=per_txn_limit_minor, daily_limit_minor=daily_limit_minor, status=status)
        return cast(t.CardProgram, self._t.request("POST", f"/v1/banks/{_q(bank_id)}/card-programs", body=body))

    def update(self, bank_id: str, program_id: str, *, name: Optional[str] = None, validity_months: Optional[int] = None,
               auth_expiry_seconds: Optional[int] = None, per_txn_limit_minor: Optional[int] = None,
               daily_limit_minor: Optional[int] = None, status: Optional[str] = None,
               clear: Optional[List[str]] = None) -> t.CardProgram:
        body = _body(name=name, validity_months=validity_months, auth_expiry_seconds=auth_expiry_seconds,
                     per_txn_limit_minor=per_txn_limit_minor, daily_limit_minor=daily_limit_minor, status=status, clear=clear)
        return cast(t.CardProgram, self._t.request("PATCH", f"/v1/banks/{_q(bank_id)}/card-programs/{_q(program_id)}", body=body))


class Cards(_Resource):
    def issue(self, *, account_id: str, program_id: Optional[str] = None, name_on_card: Optional[str] = None,
              per_txn_limit_minor: Optional[int] = None, daily_limit_minor: Optional[int] = None,
              max_fee_minor: Optional[int] = None, metadata: Optional[Dict[str, Any]] = None,
              idempotency_key: Optional[str] = None) -> t.IssueCardResult:
        """Issues a debit card on a player account, charging any card_issuance fee. The result's
        ``card_number`` and ``cvv`` are shown only now. Needs cards:write."""
        body = _body(account_id=account_id, program_id=program_id, name_on_card=name_on_card,
                     per_txn_limit_minor=per_txn_limit_minor, daily_limit_minor=daily_limit_minor,
                     max_fee_minor=max_fee_minor, metadata=metadata)
        return cast(t.IssueCardResult, self._t.request("POST", "/v1/cards", body=body, idempotent=True, idempotency_key=idempotency_key))

    def list(self, *, account_id: Optional[str] = None, player_id: Optional[str] = None,
             status: Optional[str] = None, limit: Optional[int] = None) -> List[t.Card]:
        q = {"account_id": account_id, "player_id": player_id, "status": status, "limit": limit}
        return cast(List[t.Card], self._t.request("GET", "/v1/cards", query=q)["data"])

    def get(self, card_id: str) -> t.Card:
        return cast(t.Card, self._t.request("GET", f"/v1/cards/{_q(card_id)}"))

    def update(self, card_id: str, *, name_on_card: Optional[str] = None, per_txn_limit_minor: Optional[int] = None,
               daily_limit_minor: Optional[int] = None, clear: Optional[List[str]] = None,
               metadata: Optional[Dict[str, Any]] = None) -> t.Card:
        """Changes the name on the card or its own limits (``clear`` goes back to the program's)."""
        body = _body(name_on_card=name_on_card, per_txn_limit_minor=per_txn_limit_minor,
                     daily_limit_minor=daily_limit_minor, clear=clear, metadata=metadata)
        return cast(t.Card, self._t.request("PATCH", f"/v1/cards/{_q(card_id)}", body=body))

    def block(self, card_id: str, *, reason: Optional[str] = None) -> t.Card:
        """Pauses the card: new payments are declined (card_blocked)."""
        return cast(t.Card, self._t.request("POST", f"/v1/cards/{_q(card_id)}/block", body=_body(reason=reason)))

    def unblock(self, card_id: str) -> t.Card:
        return cast(t.Card, self._t.request("POST", f"/v1/cards/{_q(card_id)}/unblock", body={}))

    def report_lost(self, card_id: str, *, reason: str = "lost") -> t.Card:
        """Reports the card ``lost`` or ``stolen``: final, and no replacement is issued.
        Payments approved before the report still capture."""
        return cast(t.Card, self._t.request("POST", f"/v1/cards/{_q(card_id)}/report-lost", body={"reason": reason}))

    def close(self, card_id: str, *, reason: Optional[str] = None) -> t.Card:
        return cast(t.Card, self._t.request("POST", f"/v1/cards/{_q(card_id)}/close", body=_body(reason=reason)))


class CardAuthorizations(_Resource):
    def authorize(self, *, amount_minor: int, card_id: Optional[str] = None, card_number: Optional[str] = None,
                  expiry_month: Optional[int] = None, expiry_year: Optional[int] = None, cvv: Optional[str] = None,
                  merchant_account_id: Optional[str] = None, merchant_account_number: Optional[str] = None,
                  reference: Optional[str] = None, description: Optional[str] = None,
                  max_fee_minor: Optional[int] = None, capture: Optional[bool] = None,
                  idempotency_key: Optional[str] = None) -> t.AuthorizeCardResult:
        """Pays a merchant by card. An approved payment is captured at once; ``capture=False``
        only reserves the money for a later ``capture`` or ``release``. A decline is not an
        exception: check ``result["authorization"]["status"]`` and ``decline_code``. Needs cards:charge."""
        _amount(amount_minor)
        body = _body(card_id=card_id, card_number=card_number, expiry_month=expiry_month, expiry_year=expiry_year, cvv=cvv,
                     merchant_account_id=merchant_account_id, merchant_account_number=merchant_account_number,
                     amount_minor=amount_minor, reference=reference, description=description, max_fee_minor=max_fee_minor,
                     capture=capture)
        return cast(t.AuthorizeCardResult, self._t.request("POST", "/v1/card-authorizations", body=body, idempotent=True,
                                                           idempotency_key=idempotency_key))

    def list(self, *, card_id: Optional[str] = None, merchant_id: Optional[str] = None, account_id: Optional[str] = None,
             status: Optional[str] = None, limit: Optional[int] = None) -> List[t.CardAuthorization]:
        q = {"card_id": card_id, "merchant_id": merchant_id, "account_id": account_id, "status": status, "limit": limit}
        return cast(List[t.CardAuthorization], self._t.request("GET", "/v1/card-authorizations", query=q)["data"])

    def get(self, authorization_id: str) -> t.CardAuthorization:
        return cast(t.CardAuthorization, self._t.request("GET", f"/v1/card-authorizations/{_q(authorization_id)}"))

    def capture(self, authorization_id: str, *, amount_minor: Optional[int] = None, max_fee_minor: Optional[int] = None,
                idempotency_key: Optional[str] = None) -> t.CaptureCardResult:
        """Settles all or part of an approved payment into the merchant account; the rest is released."""
        if amount_minor is not None:
            _amount(amount_minor)
        return cast(t.CaptureCardResult, self._t.request("POST", f"/v1/card-authorizations/{_q(authorization_id)}/capture",
                                                         body=_body(amount_minor=amount_minor, max_fee_minor=max_fee_minor),
                                                         idempotent=True, idempotency_key=idempotency_key))

    def release(self, authorization_id: str, *, reason: Optional[str] = None,
                idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Cancels an approved payment and frees its funds."""
        return cast(Dict[str, Any], self._t.request("POST", f"/v1/card-authorizations/{_q(authorization_id)}/release",
                                                    body=_body(reason=reason), idempotent=True, idempotency_key=idempotency_key))

    def refund(self, authorization_id: str, *, amount_minor: Optional[int] = None, reason: Optional[str] = None,
               idempotency_key: Optional[str] = None) -> t.RefundCardResult:
        """Refunds all (omit amount_minor) or part of a captured payment from the merchant account. Fees are not refunded."""
        if amount_minor is not None:
            _amount(amount_minor)
        return cast(t.RefundCardResult, self._t.request("POST", f"/v1/card-authorizations/{_q(authorization_id)}/refunds",
                                                        body=_body(amount_minor=amount_minor, reason=reason),
                                                        idempotent=True, idempotency_key=idempotency_key))


class WebhookEndpoints(_Resource):
    def create(self, *, url: str, description: Optional[str] = None,
               event_types: Optional[List[str]] = None) -> t.WebhookEndpoint:
        """Registers an endpoint. The result's ``secret`` is shown only now: store it and pass it to
        :func:`verify_webhook`. ``event_types`` defaults to ``["*"]``. Needs webhooks:write."""
        body = _body(url=url, description=description, event_types=event_types)
        return cast(t.WebhookEndpoint, self._t.request("POST", "/v1/webhooks/endpoints", body=body))

    def list(self) -> List[t.WebhookEndpoint]:
        return cast(List[t.WebhookEndpoint], self._t.request("GET", "/v1/webhooks/endpoints")["data"])

    def get(self, endpoint_id: str) -> t.WebhookEndpoint:
        return cast(t.WebhookEndpoint, self._t.request("GET", f"/v1/webhooks/endpoints/{_q(endpoint_id)}"))

    def update(self, endpoint_id: str, *, url: Optional[str] = None, description: Optional[str] = None,
               event_types: Optional[List[str]] = None, status: Optional[str] = None) -> t.WebhookEndpoint:
        """Changes the URL, description or event types, or pauses (``status="disabled"``) and re-enables it."""
        body = _body(url=url, description=description, event_types=event_types, status=status)
        return cast(t.WebhookEndpoint, self._t.request("PATCH", f"/v1/webhooks/endpoints/{_q(endpoint_id)}", body=body))

    def delete(self, endpoint_id: str) -> None:
        self._t.request("DELETE", f"/v1/webhooks/endpoints/{_q(endpoint_id)}")

    def rotate_secret(self, endpoint_id: str) -> t.WebhookEndpoint:
        """Issues a new secret (in the result). The old one keeps signing for 24 hours."""
        return cast(t.WebhookEndpoint, self._t.request("POST", f"/v1/webhooks/endpoints/{_q(endpoint_id)}/rotate-secret"))

    def test(self, endpoint_id: str) -> t.WebhookDelivery:
        """Sends a webhook.test event now and returns how that attempt went."""
        return cast(t.WebhookDelivery, self._t.request("POST", f"/v1/webhooks/endpoints/{_q(endpoint_id)}/test"))


class WebhookEvents(_Resource):
    def list(self, *, type: Optional[str] = None, account_id: Optional[str] = None, limit: Optional[int] = None,
             cursor: Optional[str] = None) -> t.WebhookEventPage:
        """One page of the event log, newest first (kept 30 days). Also a polling feed."""
        q = {"type": type, "account_id": account_id, "limit": limit, "cursor": cursor}
        return cast(t.WebhookEventPage, self._t.request("GET", "/v1/webhooks/events", query=q))

    def iter(self, *, type: Optional[str] = None, account_id: Optional[str] = None,
             limit: Optional[int] = None) -> Iterator[t.WebhookEvent]:
        """Every event matching the filter, newest first, fetching pages as needed."""
        cursor: Optional[str] = None
        while True:
            page = self.list(type=type, account_id=account_id, limit=limit, cursor=cursor)
            yield from page["data"]
            cursor = page.get("next_cursor")
            if not cursor:
                return

    def get(self, event_id: str) -> t.WebhookEvent:
        return cast(t.WebhookEvent, self._t.request("GET", f"/v1/webhooks/events/{_q(event_id)}"))

    def deliveries(self, event_id: str) -> List[t.WebhookDelivery]:
        """The event's deliveries, one per endpoint, with attempts and the last error."""
        return cast(List[t.WebhookDelivery], self._t.request("GET", f"/v1/webhooks/events/{_q(event_id)}/deliveries")["data"])

    def redeliver(self, event_id: str, *, endpoint_id: Optional[str] = None) -> List[t.WebhookDelivery]:
        """Sends the event again, to one endpoint or every subscribed one. Retries start over."""
        return cast(List[t.WebhookDelivery], self._t.request("POST", f"/v1/webhooks/events/{_q(event_id)}/redeliver",
                                                             body=_body(endpoint_id=endpoint_id))["data"])


class Webhooks:
    """Signed event notifications (debit and credit alerts). Verify deliveries with ``verify_webhook``."""

    def __init__(self, transport: Transport) -> None:
        self.endpoints = WebhookEndpoints(transport)
        self.events = WebhookEvents(transport)


class GameBank:
    """Runtime client for game servers, authenticated with a game API key.

    >>> gb = GameBank(api_key=os.environ["GBE_API_KEY"])  # talks to https://api.gamebank.dev
    >>> gb.transfers.create(source_account_id=a, destination_account_number=n, amount_minor=1000)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        *,
        timeout: float = 30.0,
        max_retries: int = 2,
        on_response: Optional[Callable[[ResponseInfo], None]] = None,
        sender: Optional[Sender] = None,
        _transport: Optional[Transport] = None,
    ) -> None:
        self._t = _transport or Transport(api_key, base_url, timeout=timeout, max_retries=max_retries,
                                          on_response=on_response, sender=sender)
        #: "sandbox" or "production", read from the API key's prefix.
        self.environment = self._t.environment
        #: The engine this client talks to.
        self.base_url = self._t.base_url
        self.players = Players(self._t)
        self.accounts = Accounts(self._t)
        self.funding = Funding(self._t)
        self.transfers = Transfers(self._t)
        self.holds = Holds(self._t)
        self.transactions = Transactions(self._t)
        self.banks = Banks(self._t)
        self.fees = Fees(self._t)
        self.currencies = Currencies(self._t)
        self.clock = GameClock(self._t)
        self.webhooks = Webhooks(self._t)
        self.merchants = Merchants(self._t)
        self.card_programs = CardPrograms(self._t)
        self.cards = Cards(self._t)
        self.card_authorizations = CardAuthorizations(self._t)
        self.deposit_products = DepositProducts(self._t)
        self.fixed_deposits = FixedDeposits(self._t)

    def name_enquiry(self, bank_code: str, account_number: str) -> t.NameEnquiry:
        """Confirms a recipient before a transfer: returns only the account name and status."""
        return cast(t.NameEnquiry, self._t.request("GET", "/v1/name-enquiry",
                                                   query={"bank_code": bank_code, "account_number": account_number}))

    def reconcile(self) -> t.ReconciliationReport:
        """Compares stored balances with the ledger for this game and environment."""
        return cast(t.ReconciliationReport, self._t.request("GET", "/v1/reconciliation"))


class Games(_Resource):
    def create(self, *, name: str, slug: Optional[str] = None) -> t.Game:
        return cast(t.Game, self._t.request("POST", "/v1/games", body=_body(name=name, slug=slug)))

    def list(self) -> List[t.Game]:
        return cast(List[t.Game], self._t.request("GET", "/v1/games")["data"])

    def get(self, game_id: str) -> t.Game:
        return cast(t.Game, self._t.request("GET", f"/v1/games/{_q(game_id)}"))

    def update(self, game_id: str, *, name: Optional[str] = None, slug: Optional[str] = None,
               status: Optional[str] = None) -> t.Game:
        """Renames a game, changes its slug, or suspends ("suspended") / reactivates ("active") it."""
        return cast(t.Game, self._t.request("PATCH", f"/v1/games/{_q(game_id)}", body=_body(name=name, slug=slug, status=status)))

    def delete(self, game_id: str) -> None:
        """Deletes a game permanently: its API keys are revoked at once. Ledger and audit history are kept."""
        self._t.request("DELETE", f"/v1/games/{_q(game_id)}")


class ApiKeys(_Resource):
    def issue(self, game_id: str, *, environment: str, label: Optional[str] = None,
              scopes: Optional[List[str]] = None, expires_at: Optional[str] = None) -> t.ApiKey:
        """Issues a game API key. ``secret`` is in the result once; store it on your servers."""
        body = _body(environment=environment, label=label, scopes=scopes, expires_at=expires_at)
        return cast(t.ApiKey, self._t.request("POST", f"/v1/games/{_q(game_id)}/api-keys", body=body)["api_key"])

    def list(self, game_id: str) -> List[t.ApiKey]:
        return cast(List[t.ApiKey], self._t.request("GET", f"/v1/games/{_q(game_id)}/api-keys")["data"])

    def revoke(self, game_id: str, key_id: str) -> None:
        """Revokes a key immediately."""
        self._t.request("DELETE", f"/v1/games/{_q(game_id)}/api-keys/{_q(key_id)}")


class DeveloperCredentials(_Resource):
    def list(self) -> List[t.DeveloperCredential]:
        return cast(List[t.DeveloperCredential], self._t.request("GET", "/v1/developer/credentials")["data"])

    def issue(self, *, label: Optional[str] = None, expires_at: Optional[str] = None) -> t.DeveloperCredential:
        return cast(t.DeveloperCredential, self._t.request("POST", "/v1/developer/credentials", body=_body(label=label, expires_at=expires_at)))

    def revoke(self, credential_id: str) -> None:
        self._t.request("DELETE", f"/v1/developer/credentials/{_q(credential_id)}")


class GameBankManagement:
    """Setup and CI client, authenticated with a developer credential (gbe_dev_…) or a sign-in session token."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        *,
        timeout: float = 30.0,
        max_retries: int = 2,
        on_response: Optional[Callable[[ResponseInfo], None]] = None,
        sender: Optional[Sender] = None,
    ) -> None:
        self._t = Transport(api_key, base_url, timeout=timeout, max_retries=max_retries,
                            on_response=on_response, sender=sender)
        #: The engine this client talks to.
        self.base_url = self._t.base_url
        self.games = Games(self._t)
        self.api_keys = ApiKeys(self._t)
        self.credentials = DeveloperCredentials(self._t)

    def me(self) -> t.Developer:
        """The developer this credential belongs to."""
        return cast(t.Developer, self._t.request("GET", "/v1/developer"))

    def audit_logs(self, game_id: str, *, environment: Optional[str] = None, limit: Optional[int] = None,
                   before: Optional[str] = None) -> List[t.AuditLog]:
        q = {"environment": environment, "limit": limit, "before": before}
        return cast(List[t.AuditLog], self._t.request("GET", f"/v1/games/{_q(game_id)}/audit-logs", query=q)["data"])

    def game(self, game_id: str, environment: str) -> GameBank:
        """A GameBank acting on one of your games with your developer credential: configure banks,
        currencies, limits and the clock. Moving money still needs a game API key."""
        return GameBank(_transport=self._t.with_headers({"X-Game-Id": game_id, "X-Environment": environment}))
