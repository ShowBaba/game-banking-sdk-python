"""HTTP transport: auth, idempotency keys, retries, timeouts and error mapping."""

from __future__ import annotations

import json
import os
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, NamedTuple, Optional

from .errors import GameBankError, error_for

VERSION = "0.2.0"
_RETRY_STATUSES = {500, 502, 503, 504}


class RawResponse(NamedTuple):
    status: int
    headers: Mapping[str, str]
    body: bytes


#: Sends one HTTP request. Raises OSError (or urllib.error.URLError) when no response arrives.
Sender = Callable[[str, str, Dict[str, str], Optional[bytes], float], RawResponse]


@dataclass(frozen=True)
class ResponseInfo:
    """Passed to ``on_response`` after every HTTP response, including retried ones."""

    method: str
    path: str
    status: int
    request_id: Optional[str]
    #: True when the engine returned a stored result for a repeated Idempotency-Key.
    replayed: bool
    #: 0 for the first attempt.
    attempt: int


def urllib_sender(method: str, url: str, headers: Dict[str, str], body: Optional[bytes], timeout: float) -> RawResponse:
    """The default sender, built on the standard library."""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:  # noqa: S310 - URL is the configured engine
            return RawResponse(res.status, {k.lower(): v for k, v in res.headers.items()}, res.read())
    except urllib.error.HTTPError as e:
        return RawResponse(e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read() or b"")


def environment_of(api_key: str) -> Optional[str]:
    """Reads the environment a game API key belongs to from its prefix."""
    if api_key.startswith("gbe_test_sk_"):
        return "sandbox"
    if api_key.startswith("gbe_live_sk_"):
        return "production"
    return None


def retry_delay(attempt: int, retry_after: Optional[float] = None) -> float:
    """Seconds to wait: the server's Retry-After, else exponential backoff with jitter."""
    if retry_after is not None and retry_after >= 0:
        return min(retry_after, 60.0)
    base = min(0.5 * (2**attempt), 8.0)
    return base * (0.75 + random.random() * 0.25)


class Transport:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        *,
        timeout: float = 30.0,
        max_retries: int = 2,
        on_response: Optional[Callable[[ResponseInfo], None]] = None,
        sender: Optional[Sender] = None,
        headers: Optional[Dict[str, str]] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        api_key = api_key or os.environ.get("GBE_API_KEY")
        if not api_key:
            raise GameBankError("Pass api_key or set GBE_API_KEY.", code="missing_api_key")
        base_url = base_url or os.environ.get("GBE_BASE_URL")
        if not base_url:
            raise GameBankError("Pass base_url (your engine's address) or set GBE_BASE_URL.", code="missing_base_url")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.environment = environment_of(self.api_key)
        self.timeout = timeout
        self.max_retries = max_retries
        self.on_response = on_response
        self.sender: Sender = sender or urllib_sender
        self.headers = dict(headers or {})
        self._sleep = sleep

    def with_headers(self, headers: Dict[str, str]) -> "Transport":
        """A copy that sends extra headers (used for X-Game-Id / X-Environment)."""
        t = Transport(
            self.api_key, self.base_url, timeout=self.timeout, max_retries=self.max_retries,
            on_response=self.on_response, sender=self.sender, headers={**self.headers, **headers}, sleep=self._sleep,
        )
        return t

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        body: Optional[Mapping[str, Any]] = None,
        idempotent: bool = False,
        retry_safe: bool = False,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> Any:
        url = self.base_url + path
        if query:
            q = {k: _query_value(v) for k, v in query.items() if v is not None and v != ""}
            if q:
                url += "?" + urllib.parse.urlencode(q)
        key = idempotency_key or (f"sdk_{uuid.uuid4()}" if idempotent else None)
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": f"gamebanking-sdk-python/{VERSION}",
            **self.headers,
        }
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, separators=(",", ":")).encode()
        if key:
            headers["Idempotency-Key"] = key
        safe = method in ("GET", "PUT") or bool(key) or retry_safe
        retries = self.max_retries if max_retries is None else max_retries

        attempt = 0
        while True:
            try:
                res = self.sender(method, url, headers, data, self.timeout if timeout is None else timeout)
            except (OSError, urllib.error.URLError) as e:
                timed_out = isinstance(e, (socket.timeout, TimeoutError)) or isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError))
                err: GameBankError = error_for(
                    0, "timeout" if timed_out else "connection_error",
                    f"No response from {self.base_url}" if timed_out else f"Could not reach the engine at {self.base_url}: {e}",
                )
                err.__cause__ = e
            else:
                request_id = res.headers.get("x-request-id")
                if self.on_response:
                    self.on_response(ResponseInfo(method, path, res.status, request_id, res.headers.get("idempotent-replayed") == "true", attempt))
                if 200 <= res.status < 300:
                    return self._parse(res, request_id)
                err = self._error(res, request_id)
            if attempt >= retries or not self._should_retry(err, safe):
                raise err
            self._sleep(retry_delay(attempt, err.retry_after))
            attempt += 1

    @staticmethod
    def _should_retry(err: GameBankError, safe: bool) -> bool:
        if err.status == 429:
            return True
        if not safe:
            return False
        return err.status == 0 or err.status in _RETRY_STATUSES or (err.status == 409 and err.code == "request_in_progress")

    def _parse(self, res: RawResponse, request_id: Optional[str]) -> Any:
        if res.status == 204 or not res.body:
            return None
        try:
            return json.loads(res.body)
        except ValueError:
            ctype = res.headers.get("content-type", "an unknown content type")
            raise GameBankError(
                f"Expected JSON from the engine but got {ctype}. Check that base_url ({self.base_url}) points at the engine, not a website.",
                status=res.status, code="invalid_response", request_id=request_id,
            ) from None

    @staticmethod
    def _error(res: RawResponse, request_id: Optional[str]) -> GameBankError:
        e: Dict[str, Any] = {}
        try:
            e = (json.loads(res.body) or {}).get("error") or {}
        except (ValueError, AttributeError):
            pass
        retry_after: Optional[float] = None
        try:
            ra = float(res.headers.get("retry-after", ""))
            retry_after = ra if ra > 0 else None
        except ValueError:
            pass
        return error_for(
            res.status, e.get("code") or f"http_{res.status}", e.get("message") or f"HTTP {res.status}",
            details=e.get("details") or {}, request_id=e.get("correlation_id") or request_id, retry_after=retry_after,
        )


def _query_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)
