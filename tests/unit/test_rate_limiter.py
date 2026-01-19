"""Tests for the rate limiter module."""

import asyncio

import pytest
from slack_sdk.errors import SlackApiError

from slack_assistant.slack.rate_limiter import (
    RateLimitConfig,
    RateLimiter,
    RateLimitExceededError,
    TokenBucket,
)


class TestRateLimitConfig:
    """Tests for RateLimitConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = RateLimitConfig()
        assert config.requests_per_minute == 50
        assert config.burst_size == 10
        assert config.max_concurrent == 5
        assert config.retry_max_attempts == 3
        assert config.retry_base_delay == 1.0
        assert config.retry_max_delay == 60.0
        assert config.retry_jitter == 0.5

    def test_custom_values(self):
        """Test custom configuration values."""
        config = RateLimitConfig(
            requests_per_minute=100,
            burst_size=20,
            max_concurrent=10,
        )
        assert config.requests_per_minute == 100
        assert config.burst_size == 20
        assert config.max_concurrent == 10


class TestTokenBucket:
    """Tests for TokenBucket class."""

    @pytest.fixture
    def bucket(self):
        """Create a token bucket with 10 tokens, refilling at 1/sec."""
        return TokenBucket(tokens_per_second=1.0, burst_size=10)

    async def test_acquire_within_limit(self, bucket):
        """Test that acquire succeeds when tokens are available."""
        # Should succeed immediately for first 10 tokens
        for _ in range(10):
            await bucket.acquire()

    async def test_bucket_blocks_when_empty(self, bucket):
        """Test that bucket blocks when all tokens are consumed."""
        # Consume all tokens
        for _ in range(10):
            await bucket.acquire()

        # Next acquire should block
        async def try_acquire():
            await bucket.acquire()
            return True

        # Should not complete in 0.05 seconds
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(try_acquire(), timeout=0.05)

    async def test_bucket_refills_over_time(self):
        """Test that bucket refills tokens over time."""
        # Fast bucket: 100 tokens/sec, max 2
        bucket = TokenBucket(tokens_per_second=100.0, burst_size=2)

        # Consume all tokens
        await bucket.acquire()
        await bucket.acquire()

        # Wait for refill (10ms should give us 1 token)
        await asyncio.sleep(0.02)

        # Should be able to acquire again
        async def try_acquire():
            await bucket.acquire()
            return True

        result = await asyncio.wait_for(try_acquire(), timeout=0.1)
        assert result is True


class TestRateLimiter:
    """Tests for RateLimiter class."""

    async def test_execute_simple_function(self, rate_limiter):
        """Test executing a simple async function."""

        async def simple_func():
            return 'result'

        result = await rate_limiter.execute(simple_func)
        assert result == 'result'

    async def test_execute_with_arguments(self, rate_limiter):
        """Test executing function with positional and keyword arguments."""

        async def func_with_args(a, b, c=None):
            return f'{a}-{b}-{c}'

        result = await rate_limiter.execute(func_with_args, 'x', 'y', c='z')
        assert result == 'x-y-z'

    async def test_semaphore_limits_concurrency(self, rate_limit_config):
        """Test that semaphore limits concurrent executions."""
        rate_limit_config.max_concurrent = 2
        limiter = RateLimiter(rate_limit_config)

        concurrent_count = 0
        max_concurrent_seen = 0

        async def slow_func():
            nonlocal concurrent_count, max_concurrent_seen
            concurrent_count += 1
            max_concurrent_seen = max(max_concurrent_seen, concurrent_count)
            await asyncio.sleep(0.05)
            concurrent_count -= 1
            return True

        # Launch 5 concurrent tasks
        tasks = [limiter.execute(slow_func) for _ in range(5)]
        await asyncio.gather(*tasks)

        # Should never have exceeded max_concurrent
        assert max_concurrent_seen <= 2

    async def test_respects_retry_after_header(self, rate_limit_config):
        """Test that rate limiter respects Retry-After header."""
        rate_limit_config.retry_max_attempts = 3
        rate_limit_config.retry_base_delay = 0.01
        limiter = RateLimiter(rate_limit_config)

        call_count = 0

        async def failing_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                # Simulate Slack rate limit error
                error = SlackApiError(
                    message='ratelimited',
                    response={'error': 'ratelimited', 'headers': {'Retry-After': '0.01'}},
                )
                raise error
            return 'success'

        result = await limiter.execute(failing_then_success)
        assert result == 'success'
        assert call_count == 2

    async def test_exponential_backoff_calculation(self):
        """Test exponential backoff formula."""
        config = RateLimitConfig(
            retry_base_delay=1.0,
            retry_max_delay=60.0,
            retry_jitter=0.0,  # No jitter for predictable testing
        )
        limiter = RateLimiter(config)

        # Test backoff values
        assert limiter._calculate_backoff(0) == 1.0
        assert limiter._calculate_backoff(1) == 2.0
        assert limiter._calculate_backoff(2) == 4.0
        assert limiter._calculate_backoff(3) == 8.0

        # Should cap at max_delay
        assert limiter._calculate_backoff(10) == 60.0

    async def test_jitter_applied_to_backoff(self):
        """Test that jitter is applied to backoff delays."""
        config = RateLimitConfig(
            retry_base_delay=1.0,
            retry_max_delay=60.0,
            retry_jitter=0.5,  # 50% jitter
        )
        limiter = RateLimiter(config)

        # Collect multiple backoff values to verify jitter
        backoffs = [limiter._calculate_backoff(1) for _ in range(10)]

        # With 50% jitter on base delay of 2.0, values should be in [1.0, 3.0]
        for backoff in backoffs:
            assert 1.0 <= backoff <= 3.0

        # Values should not all be the same (highly unlikely with random jitter)
        assert len(set(backoffs)) > 1

    async def test_max_retries_raises_exception(self, rate_limit_config):
        """Test that max retries exhaustion raises exception."""
        rate_limit_config.retry_max_attempts = 2
        rate_limit_config.retry_base_delay = 0.001
        limiter = RateLimiter(rate_limit_config)

        call_count = 0

        async def always_fails():
            nonlocal call_count
            call_count += 1
            error = SlackApiError(
                message='ratelimited',
                response={'error': 'ratelimited', 'headers': {}},
            )
            raise error

        with pytest.raises(RateLimitExceededError) as exc_info:
            await limiter.execute(always_fails)

        assert call_count == 2  # Initial + 1 retry
        assert 'rate limit exceeded' in str(exc_info.value).lower()

    async def test_non_rate_limit_errors_propagate(self, rate_limiter):
        """Test that non-rate-limit errors are not retried."""
        call_count = 0

        async def other_error():
            nonlocal call_count
            call_count += 1
            error = SlackApiError(
                message='channel_not_found',
                response={'error': 'channel_not_found'},
            )
            raise error

        with pytest.raises(SlackApiError) as exc_info:
            await rate_limiter.execute(other_error)

        assert call_count == 1  # Only called once, not retried
        assert exc_info.value.response['error'] == 'channel_not_found'

    async def test_concurrent_rate_limiting(self, rate_limit_config):
        """Test rate limiting under concurrent load."""
        rate_limit_config.requests_per_minute = 600  # 10 per second
        rate_limit_config.burst_size = 5
        rate_limit_config.max_concurrent = 10
        limiter = RateLimiter(rate_limit_config)

        results = []

        async def track_call():
            results.append(asyncio.get_event_loop().time())
            return True

        # Execute 10 calls concurrently
        tasks = [limiter.execute(track_call) for _ in range(10)]
        await asyncio.gather(*tasks)

        assert len(results) == 10
