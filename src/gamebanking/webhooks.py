"""Verifying webhook deliveries from the engine."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Optional, Sequence, Union, cast

from . import types as t

#: The request header that carries a delivery's timestamp and signatures.
SIGNATURE_HEADER = "GBE-Signature"


class WebhookVerificationError(Exception):
    """The request did not come from the engine, or was replayed or tampered with. Answer 400.

    ``reason`` is one of ``malformed_header``, ``timestamp_out_of_tolerance``,
    ``no_matching_signature`` or ``invalid_payload``.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def verify_webhook(
    payload: Union[bytes, str],
    signature_header: Optional[str],
    secret: Union[str, Sequence[str]],
    *,
    tolerance: int = 300,
    now: Optional[int] = None,
) -> t.WebhookEvent:
    """Checks a webhook delivery and returns its event.

    Pass the **raw** request body (before any JSON parsing), the ``GBE-Signature``
    header and your endpoint secret, or several secrets while you roll a new one out.
    Raises :class:`WebhookVerificationError` if no signature matches or the timestamp
    is more than ``tolerance`` seconds from now.

    >>> event = verify_webhook(request.body, request.headers.get("GBE-Signature"), os.environ["GBE_WEBHOOK_SECRET"])
    >>> if event["type"] == "account.debited": notify_player(event["data"])
    """
    body = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    ts = 0
    signatures = []
    for part in (signature_header or "").split(","):
        key, sep, value = part.strip().partition("=")
        if not sep:
            continue
        if key == "t" and value.isdigit():
            ts = int(value)
        elif key == "v1" and value and all(c in "0123456789abcdefABCDEF" for c in value):
            signatures.append(value.lower())
    if ts <= 0 or not signatures:
        raise WebhookVerificationError("malformed_header", f"missing or malformed {SIGNATURE_HEADER} header")
    current = int(time.time()) if now is None else now
    if abs(current - ts) > tolerance:
        raise WebhookVerificationError("timestamp_out_of_tolerance", f"the signature's timestamp is more than {tolerance}s from now")
    secrets = [secret] if isinstance(secret, str) else list(secret)
    signed = str(ts).encode() + b"." + body
    for s in secrets:
        want = hmac.new(s.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        if any(hmac.compare_digest(want, sig) for sig in signatures):
            break
    else:
        raise WebhookVerificationError("no_matching_signature", "no signature matches the secret")
    try:
        return cast(t.WebhookEvent, json.loads(body))
    except ValueError as e:
        raise WebhookVerificationError("invalid_payload", "the body is not JSON") from e
