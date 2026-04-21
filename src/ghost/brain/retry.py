"""
Retry policies for LLM API calls.

Uses tenacity for exponential backoff with jitter.
Handles 429 (rate limit), 503 (service unavailable), and timeout errors.
"""

import logging
from collections.abc import Callable
from typing import Any

import httpx
from tenacity import (
    RetryError,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ghost.constants import DEFAULT_MAX_RETRIES

logger = logging.getLogger(__name__)


def _is_retryable(exception: BaseException) -> bool:
    """Determine if an exception is retryable."""
    if isinstance(exception, httpx.HTTPStatusError):
        return exception.response.status_code in (429, 500, 502, 503, 504)
    if isinstance(exception, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout)):
        return True
    if isinstance(exception, httpx.ConnectError):
        return True
    return False


# Pre-built retry decorator for LLM calls
llm_retry = retry(
    retry=retry_if_exception_type(
        (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError)
    ),
    stop=stop_after_attempt(DEFAULT_MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=60, jitter=5),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


def with_llm_retry(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator that applies LLM retry policy to a function.

    Usage:
        @with_llm_retry
        async def call_llm(...):
            ...
    """
    return llm_retry(func)


async def retry_with_queue(
    func: Callable[..., Any], intent_queue: Any, payload: dict[str, Any], *args: Any, **kwargs: Any
) -> Any | None:
    """
    Try to call func. If it fails after retries, queue the intent.

    Args:
        func: The async function to call
        intent_queue: IntentQueue instance
        payload: Payload to queue if all retries fail

    Returns:
        Result from func, or None if queued
    """
    try:
        return await llm_retry(func)(*args, **kwargs)
    except RetryError as e:
        logger.warning(f"All retries exhausted, queuing intent: {e}")
        await intent_queue.enqueue(payload)
        return None
