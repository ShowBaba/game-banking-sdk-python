"""Server-side SDK for the Game Banking Engine API.

Keep game API keys on your servers: never ship them in a game client.
"""

from ._transport import DEFAULT_BASE_URL, VERSION, RawResponse, ResponseInfo, environment_of
from .client import GameBank, GameBankManagement
from .errors import (
    APIConnectionError,
    AuthenticationError,
    ConflictError,
    FeeChangedError,
    GameBankError,
    InsufficientFundsError,
    InvalidRequestError,
    LimitExceededError,
    NotFoundError,
    PenaltyChangedError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    UnprocessableError,
)
from .money import format_minor, to_minor
from .webhooks import SIGNATURE_HEADER, WebhookVerificationError, verify_webhook

__version__ = VERSION

__all__ = [
    "DEFAULT_BASE_URL",
    "GameBank",
    "GameBankManagement",
    "ResponseInfo",
    "RawResponse",
    "environment_of",
    "to_minor",
    "format_minor",
    "GameBankError",
    "APIConnectionError",
    "AuthenticationError",
    "ConflictError",
    "FeeChangedError",
    "InsufficientFundsError",
    "InvalidRequestError",
    "LimitExceededError",
    "NotFoundError",
    "PenaltyChangedError",
    "PermissionDeniedError",
    "RateLimitError",
    "ServerError",
    "UnprocessableError",
    "verify_webhook",
    "WebhookVerificationError",
    "SIGNATURE_HEADER",
    "__version__",
]
