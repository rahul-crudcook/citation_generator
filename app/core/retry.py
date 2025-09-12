# app/core/retry.py
"""Generic async retry utilities with backoff and optional jitter.

This module exposes:
- RetryPolicy: An immutable configuration object for retries.
- with_retries: A convenience function to execute an async callable with retries.

Typical usage:
    from app.core.retry import with_retries

    async def fetch():
        return await http_client.get("https://api.crossref.org/...")

    data = await with_retries(fetch, retries=3, backoffs=[0.25, 0.5, 1.0])

Design notes
------------
* Only retries exceptions that match `retry_exceptions` (default: Exception).
* Optional `retry_on_result` predicate lets you retry based on a "bad" result.
* Backoffs are seconds; if fewer than needed, the last value is reused.
* Optional jitter adds a random 0..jitter seconds to each sleep.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import (
    Awaitable,
    Callable,
    Iterable,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypeVar,
)

T = TypeVar("T")

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration for retry behavior.

    Attributes:
        retries: Number of *additional* attempts after the first call.
                 For example, `retries=3` means up to 4 total attempts.
        backoffs: Sequence of sleep durations (seconds) between attempts.
                  If shorter than `retries`, the last value is reused.
        retry_exceptions: Tuple of exception types that should be retried.
        retry_on_result: Optional predicate; if provided and returns True
                         for a result, the call will be retried.
        jitter: Adds a random delay in the range [0, jitter] to each backoff.
    """

    retries: int = 3
    backoffs: Sequence[float] = (0.25, 0.5, 1.0)
    retry_exceptions: Tuple[Type[Exception], ...] = (Exception,)
    retry_on_result: Optional[Callable[[T], bool]] = None
    jitter: float = 0.0

    def backoff_for_attempt(self, attempt_index: int) -> float:
        """Return the base backoff for the given attempt index (0-based).

        Example:
            With backoffs=[0.25, 0.5, 1.0] and attempt_index=4,
            returns 1.0 (the last value is reused).
        """
        if not self.backoffs:
            return 0.0
        if attempt_index < len(self.backoffs):
            return float(self.backoffs[attempt_index])
        return float(self.backoffs[-1])


async def with_retries(  # pylint: disable=too-many-branches,too-many-statements
    fn: Callable[[], Awaitable[T]],
    retries: int = 3,
    backoffs: Iterable[float] = (0.25, 0.5, 1.0),
    retry_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    retry_on_result: Optional[Callable[[T], bool]] = None,
    jitter: float = 0.0,
    logger: Optional[logging.Logger] = None,
) -> T:
    """Execute an async callable with retry/backoff.

    Args:
        fn: Zero-arg async callable to execute (e.g., a closure capturing args).
        retries: Number of *additional* attempts after the first call.
        backoffs: Iterable of base sleep durations (seconds) between attempts.
        retry_exceptions: Exception types that should be retried.
        retry_on_result: Optional predicate; if it returns True for the result,
                         a retry is performed (until attempts exhausted).
        jitter: Random jitter range (seconds) added to each backoff (0..jitter).
        logger: Optional logger; defaults to module logger.

    Returns:
        The result of the successful call.

    Raises:
        The last raised exception if attempts are exhausted, or the function's
        exception if it is not retryable.
    """
    log = logger or LOGGER

    # Normalize inputs and validate.
    backoff_list = [float(b) for b in backoffs]
    if retries < 0:
        raise ValueError("`retries` must be >= 0")
    if any(b < 0 for b in backoff_list):
        raise ValueError("All `backoffs` must be >= 0")
    if jitter < 0:
        raise ValueError("`jitter` must be >= 0")
    if not retry_exceptions:
        raise ValueError("`retry_exceptions` must contain at least one exception type")

    policy = RetryPolicy(
        retries=retries,
        backoffs=tuple(backoff_list),
        retry_exceptions=retry_exceptions,
        retry_on_result=retry_on_result,
        jitter=jitter,
    )

    attempt = 0
    # Total attempts = 1 (initial) + retries
    total_attempts = policy.retries + 1

    while True:
        try:
            result = await fn()
        except Exception as err:  # pylint: disable=broad-except
            # Filter dynamically to satisfy pylint E0712 and keep runtime behavior.
            if not isinstance(err, policy.retry_exceptions):
                raise  # Not retryable per policy; propagate immediately.

            attempt += 1
            if attempt >= total_attempts:
                # No attempts left; propagate the last retryable exception.
                raise

            # Compute backoff (with optional jitter) and sleep.
            sleep_s = policy.backoff_for_attempt(attempt - 1)
            if policy.jitter:
                sleep_s += random.random() * policy.jitter
            log.warning(
                "Retryable exception on attempt %d/%d; sleeping %.3fs: %s",
                attempt,
                total_attempts,
                sleep_s,
                err,
                exc_info=False,
            )
            await asyncio.sleep(max(0.001, sleep_s))
            continue

        # Success path: optionally retry based on the result content.
        if policy.retry_on_result and policy.retry_on_result(result):
            attempt += 1
            if attempt >= total_attempts:
                # No attempts left; return the "bad" result as-is.
                return result

            sleep_s = policy.backoff_for_attempt(attempt - 1)
            if policy.jitter:
                sleep_s += random.random() * policy.jitter
            log.info(
                "Retrying due to retry_on_result on attempt %d/%d; sleeping %.3fs",
                attempt,
                total_attempts,
                sleep_s,
            )
            await asyncio.sleep(max(0.001, sleep_s))
            continue

        # Successful and acceptable result.
        return result
