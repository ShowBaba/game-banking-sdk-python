"""Errors raised by the SDK. Branch on ``code`` for anything finer than the class."""

from __future__ import annotations

from typing import Any, Dict, Optional


class GameBankError(Exception):
    """Any failure from the Game Banking Engine or from reaching it."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 0,
        code: str = "error",
        details: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        #: HTTP status, or 0 when no response arrived.
        self.status = status
        #: The engine's stable error code, e.g. "insufficient_funds".
        self.code = code
        #: Extra context, e.g. {"available_balance": 4000, "requested_amount": 5000}.
        self.details: Dict[str, Any] = details or {}
        #: The engine's correlation ID (X-Request-Id). Quote it when reporting a problem.
        self.request_id = request_id
        #: Seconds the engine asked the caller to wait (Retry-After).
        self.retry_after = retry_after

    def __str__(self) -> str:
        rid = f" (request {self.request_id})" if self.request_id else ""
        return f"{self.code}: {self.message}{rid}"


class AuthenticationError(GameBankError):
    """401: the API key or credential is missing, wrong, expired or revoked."""


class PermissionDeniedError(GameBankError):
    """403: the credential lacks a scope, or the game or developer is suspended."""


class NotFoundError(GameBankError):
    """404: the resource does not exist in this game and environment."""


class ConflictError(GameBankError):
    """409: e.g. idempotency_key_reused, already_reversed, email_taken."""


class FeeChangedError(ConflictError):
    """409 fee_changed: the fees now total more than the request's max_fee_minor,
    e.g. the fee schedule changed after the player saw a quote. ``details["fees"]``
    lists the current charges; get a new quote."""


class InvalidRequestError(GameBankError):
    """400, 413, 415: the request itself is invalid."""


class UnprocessableError(GameBankError):
    """422 business rule failure, e.g. account_frozen, hold_not_active."""


class InsufficientFundsError(UnprocessableError):
    """422 insufficient_funds: the source account's available balance is too low."""


class LimitExceededError(UnprocessableError):
    """422 limit_exceeded: a per-transaction or per-game-day cap would be exceeded."""


class RateLimitError(GameBankError):
    """429: slow down; see retry_after."""


class ServerError(GameBankError):
    """5xx: the engine failed. Nothing was committed for a 500."""


class APIConnectionError(GameBankError):
    """No response: network failure or timeout (status 0)."""


def error_for(status: int, code: str, message: str, **kw: Any) -> GameBankError:
    """Builds the right error subtype from a status and engine error code."""
    cls: type = GameBankError
    if status == 0:
        cls = APIConnectionError
    elif status == 401:
        cls = AuthenticationError
    elif status == 403:
        cls = PermissionDeniedError
    elif status == 404:
        cls = NotFoundError
    elif status == 409:
        cls = FeeChangedError if code == "fee_changed" else ConflictError
    elif status == 429:
        cls = RateLimitError
    elif status == 422:
        cls = {"insufficient_funds": InsufficientFundsError, "limit_exceeded": LimitExceededError}.get(code, UnprocessableError)
    elif status >= 500:
        cls = ServerError
    elif status >= 400:
        cls = InvalidRequestError
    return cls(message, status=status, code=code, **kw)
