# Slack Assistant

A tool to integrate AI with daily Slack activities and tasks. Acts as a user client (not a bot) to track messages, reactions, and reminders.

## Features

- Integrates with Slack API as a user client
- Polls all channels for messages and reactions
- Does not mark messages as read
- PostgreSQL + pgvector for data storage and vector search
- SQLAlchemy ORM with Alembic migrations

## Prerequisites

- Python 3.14+
- Docker and Docker Compose
- [uv](https://github.com/astral-sh/uv) package manager
- Slack User OAuth Token (xoxp-...)

## Quick Start

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd slack-assistant
uv sync
```

### 2. Set up environment variables

Create a `.envrc` file (or export directly):

```bash
export SLACK_USER_TOKEN=xoxp-your-token-here
```

### 3. Provision the database

```bash
uv run python scripts/provision.py --reset
```

This will:
- Start PostgreSQL with pgvector in Docker
- Run Alembic migrations to create the schema

### 4. Run initial Slack sync

```bash
uv run python scripts/initial_sync.py
```

This syncs all your channels and recent messages. It may take a while depending on workspace size.

### 5. Start the daemon

```bash
uv run slack-assistant daemon
```

The daemon polls Slack every 60 seconds for new messages.

### 6. Check status

```bash
uv run slack-assistant status
```

## CLI Commands

```bash
# Start the background sync daemon
uv run slack-assistant daemon

# Run a one-time sync
uv run slack-assistant sync

# Get status report (mentions, DMs, threads)
uv run slack-assistant status

# Search messages
uv run slack-assistant search "query"
```

## Scripts

| Script | Description |
|--------|-------------|
| `scripts/provision.py` | Set up database (Docker + migrations) |
| `scripts/initial_sync.py` | Initial Slack data sync |
| `scripts/export_data.py` | Export database to JSONL backup |
| `scripts/import_data.py` | Import database from JSONL backup |

### Provision Options

```bash
# Full reset (removes all data)
uv run python scripts/provision.py --reset

# Skip Docker (if DB is already running)
uv run python scripts/provision.py --skip-docker
```

### Export Data

```bash
uv run python scripts/export_data.py
```

Exports all data to `exports/slack_data_YYYYMMDD_HHMMSS/` directory with separate `.jsonl` files for each table (one JSON object per line for memory efficiency).

### Import Data

```bash
uv run python scripts/import_data.py exports/slack_data_YYYYMMDD_HHMMSS/
```

Imports data from a JSONL backup directory. Uses upsert to handle existing records gracefully.

## Database

The application uses PostgreSQL with pgvector extension for vector similarity search.

### Running migrations

```bash
# Apply all migrations
uv run alembic upgrade head

# Check current migration
uv run alembic current

# Create a new migration
uv run alembic revision --autogenerate -m "description"
```

### Schema

- `channels` - Slack channels/conversations
- `users` - User cache
- `messages` - Messages with metadata
- `reactions` - Reactions on messages
- `message_embeddings` - Vector embeddings for search
- `sync_state` - Per-channel sync cursors
- `reminders` - Slack reminders (Later section)

## Development

### Running tools

Always use `uv run` to run Python tools:

```bash
uv run ruff check .
uv run ruff format .
uv run pytest
uv run alembic upgrade head
```

### Project Structure

```
slack_assistant/
├── cli/           # CLI commands
├── db/            # Database models, repository, migrations
│   └── alembic/   # Alembic migrations
├── services/      # Business logic (status, search, embeddings)
└── slack/         # Slack client and poller
scripts/
├── provision.py      # Database setup
├── initial_sync.py   # Initial Slack sync
├── export_data.py    # Data export (JSONL)
└── import_data.py    # Data import (JSONL)
```

## Required Slack Scopes

Your Slack OAuth token needs these scopes:

```
channels:read, channels:history    # Public channels
groups:read, groups:history        # Private channels
im:read, im:history                # DMs
mpim:read, mpim:history            # Group DMs
users:read                         # User info
reactions:read                     # Reactions
reminders:read                     # Later tasks
search:read                        # Search (optional)
```

## License

MIT
