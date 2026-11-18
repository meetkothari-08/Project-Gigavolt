"""Small retry helper shared by the database clients."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from functools import wraps
from typing import TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


def retry_with_reconnect(
    retryable: tuple[type[BaseException], ...],
    *,
    attempts: int = 3,
    backoff_seconds: float = 0.5,
    should_retry: Callable[[BaseException], bool] | None = None,
    label: str = "operation",
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Retry a method after transient failures, calling ``self.reconnect()``.

    The wrapped method must belong to an object that exposes ``reconnect()``.
    Backoff is linear (0.5 s, 1.0 s, ...). ``should_retry`` can veto a retry
    for exceptions that match ``retryable`` but are not transient.
    """

    def decorator(function: Callable[..., T]) -> Callable[..., T]:
        @wraps(function)
        def wrapper(self, *args, **kwargs):
            for attempt in range(1, attempts + 1):
                try:
                    return function(self, *args, **kwargs)
                except retryable as exc:
                    if should_retry is not None and not should_retry(exc):
                        raise
                    if attempt == attempts:
                        logger.exception(
                            "%s %s failed after %s attempts",
                            label, function.__name__, attempts,
                        )
                        raise
                    logger.warning(
                        "%s %s failed (attempt %s/%s): %s. Reconnecting.",
                        label, function.__name__, attempt, attempts, exc,
                    )
                    self.reconnect()
                    time.sleep(backoff_seconds * attempt)
            raise RuntimeError("unreachable")

        return wrapper

    return decorator
