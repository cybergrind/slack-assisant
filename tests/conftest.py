"""Shared pytest fixtures for Slack Assistant tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from slack_assistant.slack.rate_limiter import RateLimitConfig, RateLimiter


@pytest.fixture
def rate_limit_config():
    """Test configuration with fast timing for tests."""
    return RateLimitConfig(
        requests_per_minute=60,  # 1 per second
        burst_size=5,
        max_concurrent=3,
        retry_max_attempts=3,
        retry_base_delay=0.01,  # Fast for testing
        retry_max_delay=0.1,
        retry_jitter=0.0,  # Deterministic for testing
    )


@pytest.fixture
def rate_limiter(rate_limit_config):
    """RateLimiter instance with test configuration."""
    return RateLimiter(rate_limit_config)


@pytest.fixture
def mock_slack_web_client():
    """Mocked AsyncWebClient for testing."""
    client = MagicMock()
    client.conversations_list = AsyncMock(return_value={'ok': True, 'channels': []})
    client.conversations_history = AsyncMock(return_value={'ok': True, 'messages': []})
    client.conversations_replies = AsyncMock(return_value={'ok': True, 'messages': []})
    client.users_info = AsyncMock(return_value={'ok': True, 'user': {}})
    client.auth_test = AsyncMock(
        return_value={
            'ok': True,
            'user_id': 'U123456',
            'user': 'testuser',
            'team_id': 'T123456',
        }
    )
    return client
