"""Rate limiting for Slack API calls.

Implements token bucket algorithm with semaphore-based concurrency control
and exponential backoff retry logic.
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, TypeVar

from slack_sdk.errors import SlackApiError


logger = logging.getLogger(__name__)

T = TypeVar('T')


class RateLimitExceededError(Exception):
    """Raised when rate limit retries are exhausted."""

    def __init__(self, message: str, attempts: int):
        super().__init__(message)
        self.attempts = attempts


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting.

    Attributes:
        requests_per_minute: Target sustained request rate.
        burst_size: Maximum burst capacity (token bucket size).
        max_concurrent: Maximum concurrent requests allowed.
        retry_max_attempts: Maximum retry attempts for rate-limited requests.
        retry_base_delay: Base delay for exponential backoff (seconds).
        retry_max_delay: Maximum delay between retries (seconds).
        retry_jitter: Jitter factor (0.0-1.0) to add randomness to delays.
    """

    requests_per_minute: int = 50
    burst_size: int = 10
    max_concurrent: int = 5
    retry_max_attempts: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 60.0
    retry_jitter: float = 0.5


# Slack API tier-based rate limits
# https://api.slack.com/docs/rate-limits
SLACK_RATE_LIMITS: dict[str, RateLimitConfig] = {
    'conversations.list': RateLimitConfig(requests_per_minute=20, burst_size=5),  # Tier 2
    'conversations.history': RateLimitConfig(requests_per_minute=50, burst_size=10),  # Tier 3
    'conversations.replies': RateLimitConfig(requests_per_minute=50, burst_size=10),  # Tier 3
    'users.info': RateLimitConfig(requests_per_minute=100, burst_size=20),  # Tier 4
    'users.list': RateLimitConfig(requests_per_minute=20, burst_size=5),  # Tier 2
    'search.messages': RateLimitConfig(requests_per_minute=20, burst_size=5),  # Tier 2
    'reminders.list': RateLimitConfig(requests_per_minute=20, burst_size=5),  # Tier 2
    'auth.test': RateLimitConfig(requests_per_minute=100, burst_size=20),  # Tier 4
}


class TokenBucket:
    """Token bucket rate limiter.

    Allows bursts up to bucket capacity while maintaining average rate.
    Tokens are refilled continuously based on elapsed time.
    """

    def __init__(self, tokens_per_second: float, burst_size: int):
        """Initialize token bucket.

        Args:
            tokens_per_second: Rate at which tokens are refilled.
            burst_size: Maximum number of tokens in bucket.
        """
        self._tokens_per_second = tokens_per_second
        self._burst_size = burst_size
        self._tokens = float(burst_size)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire a token, blocking if none available."""
        while True:
            async with self._lock:
                self._refill()

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                # Calculate wait time for next token
                wait_time = (1.0 - self._tokens) / self._tokens_per_second

            # Wait outside lock to allow concurrent token consumption
            await asyncio.sleep(wait_time)

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._burst_size, self._tokens + elapsed * self._tokens_per_second)
        self._last_refill = now


class RateLimiter:
    """Rate limiter for Slack API calls.

    Combines token bucket rate limiting with semaphore-based concurrency
    control and exponential backoff retry logic.
    """

    def __init__(self, config: RateLimitConfig | None = None):
        """Initialize rate limiter.

        Args:
            config: Rate limit configuration. Uses defaults if not provided.
        """
        self._config = config or RateLimitConfig()
        self._bucket = TokenBucket(
            tokens_per_second=self._config.requests_per_minute / 60.0,
            burst_size=self._config.burst_size,
        )
        self._semaphore = asyncio.Semaphore(self._config.max_concurrent)

    async def execute(
        self,
        func: Callable[..., Coroutine[Any, Any, T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Execute an async function with rate limiting and retry logic.

        Args:
            func: Async function to execute.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            Result of the function call.

        Raises:
            RateLimitExceededError: If max retries exceeded.
            SlackApiError: For non-rate-limit API errors.
        """
        attempt = 0

        while True:
            # Wait for rate limit token
            await self._bucket.acquire()

            # Wait for concurrency slot
            async with self._semaphore:
                try:
                    return await func(*args, **kwargs)

                except SlackApiError as e:
                    if e.response.get('error') != 'ratelimited':
                        # Non-rate-limit error, propagate immediately
                        raise

                    attempt += 1
                    if attempt >= self._config.retry_max_attempts:
                        raise RateLimitExceededError(
                            f'Rate limit exceeded after {attempt} attempts',
                            attempts=attempt,
                        ) from e

                    # Get Retry-After header if available
                    retry_after = self._get_retry_after(e)
                    delay = retry_after if retry_after else self._calculate_backoff(attempt)

                    logger.warning(
                        f'Rate limited (attempt {attempt}/{self._config.retry_max_attempts}), retrying in {delay:.2f}s'
                    )

                    await asyncio.sleep(delay)

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff delay with jitter.

        Args:
            attempt: Current attempt number (0-indexed).

        Returns:
            Delay in seconds.
        """
        # Exponential backoff: base * 2^attempt
        delay = self._config.retry_base_delay * (2**attempt)

        # Apply jitter
        if self._config.retry_jitter > 0:
            jitter_range = delay * self._config.retry_jitter
            delay = delay - jitter_range + (random.random() * jitter_range * 2)

        # Cap at max delay
        return min(delay, self._config.retry_max_delay)

    def _get_retry_after(self, error: SlackApiError) -> float | None:
        """Extract Retry-After header from Slack error response.

        Args:
            error: SlackApiError exception.

        Returns:
            Retry delay in seconds, or None if not available.
        """
        try:
            headers = error.response.get('headers', {})
            retry_after = headers.get('Retry-After')
            if retry_after:
                return float(retry_after)
        except (ValueError, TypeError, AttributeError):
            pass
        return None


def get_rate_limiter(method_name: str | None = None) -> RateLimiter:
    """Get a rate limiter for a specific Slack API method.

    Args:
        method_name: Slack API method name (e.g., 'conversations.history').
                    If None, uses default configuration.

    Returns:
        RateLimiter configured for the method's tier.
    """
    if method_name and method_name in SLACK_RATE_LIMITS:
        config = SLACK_RATE_LIMITS[method_name]
    else:
        config = RateLimitConfig()

    return RateLimiter(config)
