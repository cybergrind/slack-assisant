#!/usr/bin/env python3
"""Provision development environment.

1. Stop and remove existing containers (with volumes)
2. Start PostgreSQL container
3. Wait for database readiness
4. Run Alembic migrations

Note: This script does NOT run initial Slack sync.
Use scripts/initial_sync.py for that.
"""

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path


# Get project root
PROJECT_ROOT = Path(__file__).parent.parent


async def wait_for_postgres(max_attempts: int = 30) -> bool:
    """Wait for PostgreSQL to accept connections."""
    print('   Waiting for PostgreSQL to be ready...')
    for i in range(max_attempts):
        result = subprocess.run(  # noqa: ASYNC221
            ['docker', 'exec', 'slack_assistant_db', 'pg_isready', '-U', 'slack_assistant'],
            capture_output=True,
        )
        if result.returncode == 0:
            return True
        await asyncio.sleep(1)
        if (i + 1) % 5 == 0:
            print(f'   Still waiting... ({i + 1}/{max_attempts})')
    return False


def run_command(cmd: list[str], description: str, cwd: Path | None = None) -> bool:
    """Run a command and return success status."""
    print(f'   Running: {" ".join(cmd)}')
    result = subprocess.run(cmd, cwd=cwd or PROJECT_ROOT)
    if result.returncode != 0:
        print(f'   ERROR: {description} failed with code {result.returncode}')
        return False
    return True


async def main():
    """Run provisioning steps."""
    parser = argparse.ArgumentParser(description='Provision Slack Assistant development environment')
    parser.add_argument('--reset', action='store_true', help='Reset database (remove volumes)')
    parser.add_argument('--skip-docker', action='store_true', help='Skip Docker operations (assume DB is running)')
    args = parser.parse_args()

    print('=' * 60)
    print('  Provisioning Slack Assistant')
    print('=' * 60)
    print()

    # 1. Reset Docker containers (optional)
    if not args.skip_docker:
        if args.reset:
            print('1. Resetting Docker containers (with volumes)...')
            run_command(['docker', 'compose', 'down', '-v'], 'docker compose down', cwd=PROJECT_ROOT)
        else:
            print('1. Stopping Docker containers...')
            run_command(['docker', 'compose', 'down'], 'docker compose down', cwd=PROJECT_ROOT)

        # 2. Start PostgreSQL container
        print('\n2. Starting PostgreSQL container...')
        if not run_command(['docker', 'compose', 'up', '-d', 'postgres'], 'docker compose up', cwd=PROJECT_ROOT):
            sys.exit(1)

        # 3. Wait for PostgreSQL
        print('\n3. Waiting for PostgreSQL...')
        if not await wait_for_postgres():
            print('   ERROR: PostgreSQL failed to start')
            sys.exit(1)
        print('   PostgreSQL is ready!')
    else:
        print('1-3. Skipping Docker operations (--skip-docker)')

    # 4. Run migrations
    print('\n4. Running Alembic migrations...')
    if not run_command(['uv', 'run', 'alembic', 'upgrade', 'head'], 'alembic upgrade', cwd=PROJECT_ROOT):
        sys.exit(1)
    print('   Migrations applied!')

    print()
    print('=' * 60)
    print('  Provisioning Complete!')
    print('=' * 60)
    print()
    print('Next steps:')
    print('  1. Set SLACK_USER_TOKEN environment variable')
    print('  2. Run initial sync: uv run python scripts/initial_sync.py')
    print('  3. Start daemon: uv run slack-assistant daemon')
    print('  4. Or check status: uv run slack-assistant status')


if __name__ == '__main__':
    asyncio.run(main())
