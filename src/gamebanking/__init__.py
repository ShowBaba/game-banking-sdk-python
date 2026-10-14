"""Server-side SDK for the Game Banking Engine API.

Keep game API keys on your servers: never ship them in a game client.
"""

from ._transport import VERSION, RawResponse, ResponseInfo, environment_of
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
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    UnprocessableError,
)
from .money import format_minor, to_minor

__version__ = VERSION

__all__ = [
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
    "PermissionDeniedError",
    "RateLimitError",
    "ServerError",
    "UnprocessableError",
    "__version__",
]
