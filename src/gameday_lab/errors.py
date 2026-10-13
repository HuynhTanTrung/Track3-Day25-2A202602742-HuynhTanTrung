"""Part A1 — Error classification."""

from __future__ import annotations

from enum import Enum

from gameday_lab.sim.contracts import ProviderError


class ErrorKind(str, Enum):
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    OVERLOADED = "overloaded"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    CLIENT_ERROR = "client_error"


def classify(err: ProviderError) -> ErrorKind:
    """Map a provider error to an ErrorKind."""
    # Client gave up (status 0) or explicit request timeout.
    if err.status == 0 or err.status == 408:
        return ErrorKind.TIMEOUT

    # 429: distinguish tenant rate-limit (retryable, has retry-after) from
    # billing/quota exhaustion (not retryable, fail over to a different account).
    if err.status == 429:
        if err.code == "insufficient_quota":
            return ErrorKind.QUOTA_EXHAUSTED
        return ErrorKind.RATE_LIMITED

    # Provider is shedding load or down.
    if err.status in (503, 529):
        return ErrorKind.OVERLOADED

    # Any other 5xx (500/502/504/...) -> transient server error.
    if 500 <= err.status < 600:
        return ErrorKind.SERVER_ERROR

    # Everything else (4xx): 400/401/403/404/422 — our bug or misconfig.
    return ErrorKind.CLIENT_ERROR


def is_retryable(kind: ErrorKind) -> bool:
    """May we try *the same provider* again for this call (after a delay)?"""
    return kind in (
        ErrorKind.RATE_LIMITED,
        ErrorKind.OVERLOADED,
        ErrorKind.SERVER_ERROR,
        ErrorKind.TIMEOUT,
    )


def counts_toward_breaker(kind: ErrorKind) -> bool:
    """Does this error say something about the *health* of the provider?"""
    return kind in (
        ErrorKind.OVERLOADED,
        ErrorKind.SERVER_ERROR,
        ErrorKind.TIMEOUT,
    )


def failover_helps(kind: ErrorKind) -> bool:
    """Would sending the same request to *another* provider help?"""
    return kind is not ErrorKind.CLIENT_ERROR