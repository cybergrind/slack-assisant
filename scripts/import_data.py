#!/usr/bin/env python3
"""Import database data from JSONL backup.

Imports: channels, users, messages, reactions, reminders, sync_state
Reads from .jsonl files (one JSON object per line) for memory efficiency.
"""

import argparse
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from slack_assistant.db.connection import close_db, get_session, init_db
from slack_assistant.db.models import Channel, Message, Reaction, Reminder, SyncState, User


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)


def parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO format datetime string."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def deserialize_row(data: dict[str, Any], model: type) -> dict[str, Any]:
    """Convert JSON data to model-compatible dictionary."""
    result = {}
    for column in model.__table__.columns:
        if column.name not in data:
            continue

        value = data[column.name]

        # Handle datetime columns
        if hasattr(column.type, 'python_type') and column.type.python_type == datetime:
            value = parse_datetime(value)

        result[column.name] = value

    return result


async def import_table_jsonl(
    model: type,
    input_file: Path,
    batch_size: int = 100,
) -> int:
    """Import rows from a JSONL file into a table."""
    if not input_file.exists():
        logger.warning(f'File not found: {input_file}')
        return 0

    count = 0
    batch = []

    # Get the metadata column reference for tables that have it
    metadata_col = None
    if hasattr(model, 'metadata_'):
        metadata_col = model.__table__.c.metadata

    async with get_session() as session:
        with open(input_file) as f:  # noqa: ASYNC230
            for line in f:
                line = line.strip()
                if not line:
                    continue

                data = json.loads(line)
                row_data = deserialize_row(data, model)

                # Handle metadata column separately due to SQLAlchemy name conflict
                metadata_value = row_data.pop('metadata', None)

                batch.append((row_data, metadata_value))
                count += 1

                if len(batch) >= batch_size:
                    await _insert_batch(session, model, batch, metadata_col)
                    batch = []

            # Insert remaining rows
            if batch:
                await _insert_batch(session, model, batch, metadata_col)

        await session.commit()

    return count


async def _insert_batch(session, model: type, batch: list, metadata_col) -> None:
    """Insert a batch of rows with upsert."""
    for row_data, metadata_value in batch:
        # Build the insert statement
        if metadata_col is not None and metadata_value is not None:
            stmt = insert(model).values(**row_data).values({metadata_col: metadata_value})
        else:
            stmt = insert(model).values(**row_data)

        # Get primary key columns for conflict resolution
        pk_cols = [col.name for col in model.__table__.primary_key.columns]

        # Build update set (all non-pk columns)
        update_cols = {
            col.name: getattr(stmt.excluded, col.name)
            for col in model.__table__.columns
            if col.name not in pk_cols
        }

        # Add metadata to update if present
        if metadata_col is not None and metadata_value is not None:
            update_cols[metadata_col] = stmt.excluded.metadata

        stmt = stmt.on_conflict_do_update(index_elements=pk_cols, set_=update_cols)

        await session.execute(stmt)


async def main():
    """Run the import."""
    parser = argparse.ArgumentParser(description='Import Slack data from JSONL backup')
    parser.add_argument('export_dir', type=Path, help='Path to export directory containing .jsonl files')
    parser.add_argument('--batch-size', type=int, default=100, help='Batch size for inserts (default: 100)')
    args = parser.parse_args()

    if not args.export_dir.exists():
        logger.error(f'Export directory not found: {args.export_dir}')
        return

    # Check for metadata file
    metadata_file = args.export_dir / 'metadata.json'
    if metadata_file.exists():
        with open(metadata_file) as f:  # noqa: ASYNC230
            metadata = json.load(f)
        logger.info(f"Importing from backup created at: {metadata.get('exported_at', 'unknown')}")

    # Initialize database
    await init_db()

    print('Importing data to database...')
    print(f'Source directory: {args.export_dir}')
    print()

    try:
        # Import tables in order (respecting foreign key constraints)
        tables = [
            (Channel, 'channels'),
            (User, 'users'),
            (Message, 'messages'),
            (Reaction, 'reactions'),
            (Reminder, 'reminders'),
            (SyncState, 'sync_state'),
        ]

        counts = {}
        for model, name in tables:
            input_file = args.export_dir / f'{name}.jsonl'
            count = await import_table_jsonl(model, input_file, args.batch_size)
            counts[name] = count
            print(f'  {name}: {count} records imported')

        print()
        print('Import complete!')
        print()
        print('Summary:')
        for name, count in counts.items():
            print(f'  {name:15} {count:>6}')

    finally:
        await close_db()


if __name__ == '__main__':
    asyncio.run(main())
