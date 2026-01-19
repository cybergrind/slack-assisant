"""Sample Slack API response fixtures for testing."""

SAMPLE_CHANNEL_HISTORY = {
    'ok': True,
    'messages': [
        {
            'type': 'message',
            'user': 'U123456',
            'text': 'Hello world!',
            'ts': '1234567890.123456',
        },
        {
            'type': 'message',
            'user': 'U789012',
            'text': 'How are you?',
            'ts': '1234567891.123456',
            'thread_ts': '1234567890.123456',
            'reply_count': 2,
        },
    ],
    'has_more': False,
    'response_metadata': {
        'next_cursor': '',
    },
}


SAMPLE_CONVERSATIONS_LIST = {
    'ok': True,
    'channels': [
        {
            'id': 'C123456',
            'name': 'general',
            'is_channel': True,
            'is_member': True,
            'created': 1600000000,
        },
        {
            'id': 'C789012',
            'name': 'random',
            'is_channel': True,
            'is_member': True,
            'created': 1600000100,
        },
    ],
    'response_metadata': {
        'next_cursor': '',
    },
}


SAMPLE_USER_INFO = {
    'ok': True,
    'user': {
        'id': 'U123456',
        'name': 'jsmith',
        'real_name': 'John Smith',
        'is_bot': False,
        'profile': {
            'display_name': 'John',
        },
    },
}


SAMPLE_RATE_LIMITED_RESPONSE = {
    'ok': False,
    'error': 'ratelimited',
}
