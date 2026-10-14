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
    def open(self, *, bank_id: str, player_id: str, account_type: Optional[str] = None,
             account_name: Optional[str] = None, currency: Optional[str] = None,
             metadata: Optional[Dict[str, Any]] = None) -> t.Account:
        body = _body(bank_id=bank_id, player_id=player_id, account_type=account_type,
                     account_name=account_name, currency=currency, metadata=metadata)
        return cast(t.Account, self._t.request("POST", "/v1/accounts", body=body))

    def get(self, account_id: str) -> t.Account:
        return cast(t.Account, self._t.request("GET", f"/v1/accounts/{_q(account_id)}"))

    def list(self, *, bank_id: Optional[str] = None, player_id: Optional[str] = None,
             include_system: bool = False, limit: Optional[int] = None) -> List[t.Account]:
        q = {"bank_id": bank_id, "player_id": player_id, "include_system": include_system or None, "limit": limit}
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


class GameBank:
    """Runtime client for game servers, authenticated with a game API key.

    >>> gb = GameBank(api_key=os.environ["GBE_API_KEY"], base_url="https://engine.example.com")
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
