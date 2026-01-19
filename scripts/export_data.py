#!/usr/bin/env python3
"""Export database data to JSONL for backup/migration.

Exports: channels, users, messages, reactions, reminders, sync_state
Each table is exported to a separate .jsonl file (one JSON object per line).
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from slack_assistant.db.connection import close_db, get_session, init_db
from slack_assistant.db.models import Channel, Message, Reaction, Reminder, SyncState, User


def serialize_value(obj: Any) -> Any:
    """Serialize a value for JSON output."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, list):
        return [serialize_value(item) for item in obj]
    if isinstance(obj, dict):
        return {k: serialize_value(v) for k, v in obj.items()}
    return obj


# Mapping from database column names to Python attribute names
COLUMN_TO_ATTR = {
    'metadata': 'metadata_',
}


def model_to_dict(row: Any, model: type) -> dict[str, Any]:
    """Convert a SQLAlchemy model instance to a dictionary."""
    result = {}
    for column in model.__table__.columns:
        # Use the mapped attribute name if it exists
        attr_name = COLUMN_TO_ATTR.get(column.name, column.name)
        value = getattr(row, attr_name)
        # Use original column name as the key
        result[column.name] = serialize_value(value)
    return result


async def export_table_jsonl(model: type, output_file: Path) -> int:
    """Export all rows from a table to a JSONL file."""
    count = 0
    async with get_session() as session:
        result = await session.execute(select(model))
        rows = result.scalars().all()

        with open(output_file, 'w') as f:  # noqa: ASYNC230
            for row in rows:
                data = model_to_dict(row, model)
                f.write(json.dumps(data) + '\n')
                count += 1

    return count


async def main():
    """Run the export."""
    # Initialize database
    await init_db()

    output_dir = Path('exports')
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    export_dir = output_dir / f'slack_data_{timestamp}'
    export_dir.mkdir(exist_ok=True)

    print('Exporting data from database...')
    print(f'Output directory: {export_dir}')
    print()

    try:
        # Export all tables to separate JSONL files
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
            output_file = export_dir / f'{name}.jsonl'
            count = await export_table_jsonl(model, output_file)
            counts[name] = count
            print(f'  {name}: {count} records -> {output_file.name}')

        # Write metadata file
        metadata = {
            'exported_at': datetime.now().isoformat(),
            'counts': counts,
        }
        metadata_file = export_dir / 'metadata.json'
        with open(metadata_file, 'w') as f:  # noqa: ASYNC230
            json.dump(metadata, f, indent=2)

        print()
        print(f'Export complete: {export_dir}')
        print()
        print('Summary:')
        for name, count in counts.items():
            print(f'  {name:15} {count:>6}')

    finally:
        await close_db()


if __name__ == '__main__':
    asyncio.run(main())
