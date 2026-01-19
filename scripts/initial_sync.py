#!/usr/bin/env python3
"""Run initial Slack sync to populate the database.

This script performs a one-time sync of all channels and messages from Slack.
It can take a long time depending on the number of channels and messages.

Prerequisites:
- Database must be running and migrated (run provision.py first)
- SLACK_USER_TOKEN environment variable must be set
"""

import argparse
import asyncio
import logging
import sys

from slack_assistant.config import get_config
from slack_assistant.db.connection import close_db, init_db
from slack_assistant.db.repository import Repository
from slack_assistant.slack.client import SlackClient
from slack_assistant.slack.poller import SlackPoller


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)


async def main():
    """Run initial sync."""
    parser = argparse.ArgumentParser(description='Run initial Slack sync')
    parser.add_argument(
        '--channels-only',
        action='store_true',
        help='Only sync channel list, skip messages',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=100,
        help='Maximum messages per channel (default: 100)',
    )
    args = parser.parse_args()

    config = get_config()

    if not config.slack_user_token:
        logger.error('SLACK_USER_TOKEN environment variable is not set')
        sys.exit(1)

    print('=' * 60)
    print('  Initial Slack Sync')
    print('=' * 60)
    print()

    try:
        # Initialize database
        logger.info('Connecting to database...')
        await init_db()

        # Initialize Slack client
        client = SlackClient(config.slack_user_token)
        await client.connect()
        logger.info(f'Authenticated as {client.user_name} (ID: {client.user_id})')

        # Create repository and poller
        repository = Repository()
        poller = SlackPoller(client, repository, poll_interval=60)

        # Sync channels
        logger.info('Syncing channels...')
        await poller._sync_channels()

        if not args.channels_only:
            # Sync messages for all channels
            logger.info('Syncing messages (this may take a while)...')
            channels = await repository.get_all_channels()
            total_messages = 0

            for i, channel in enumerate(channels, 1):
                try:
                    await poller._sync_channel_messages(channel.id)
                    if (i % 10) == 0:
                        logger.info(f'Progress: {i}/{len(channels)} channels synced')
                except Exception as e:
                    logger.warning(f'Failed to sync channel {channel.name}: {e}')

            # Get final count
            from sqlalchemy import func, select

            from slack_assistant.db.connection import get_session
            from slack_assistant.db.models import Message

            async with get_session() as session:
                result = await session.execute(select(func.count()).select_from(Message))
                total_messages = result.scalar_one()

            logger.info(f'Synced {total_messages} messages total')

        print()
        print('=' * 60)
        print('  Initial Sync Complete!')
        print('=' * 60)
        print()
        print('Next steps:')
        print('  - Start daemon: uv run slack-assistant daemon')
        print('  - Check status: uv run slack-assistant status')

    except Exception as e:
        logger.error(f'Sync failed: {e}')
        sys.exit(1)
    finally:
        await close_db()


if __name__ == '__main__':
    asyncio.run(main())
