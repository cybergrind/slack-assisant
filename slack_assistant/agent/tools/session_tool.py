"""Session management tool for tracking processed items."""

from typing import Any

from slack_assistant.agent.tools.base import BaseTool
from slack_assistant.session import (
    ConversationSummary,
    ItemDisposition,
    SessionState,
    SessionStorage,
)


class SessionTool(BaseTool):
    """Tool for managing session state and tracking processed items."""

    def __init__(self, storage: SessionStorage, session: SessionState):
        """Initialize the session tool.

        Args:
            storage: Session storage backend.
            session: Current session state.
        """
        self._storage = storage
        self._session = session

    @property
    def name(self) -> str:
        return 'manage_session'

    @property
    def description(self) -> str:
        return """Manage session state and track processed items.

Actions:
- get_session_info: Get current session information (ID, start time, processed items count)
- mark_item_reviewed: Mark a message as reviewed/seen
- mark_item_deferred: Mark a message to handle later
- mark_item_acted_on: Mark a message as acted upon
- set_focus: Set the current focus/topic being worked on
- save_summary: Save a conversation summary with key topics and pending follow-ups
- get_processed_items: List all items processed in this session

Use this tool to:
- Track which items have been reviewed during the conversation
- Set your current focus so it persists across interactions
- Save summaries when the user leaves so you can resume later"""

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            'type': 'object',
            'properties': {
                'action': {
                    'type': 'string',
                    'enum': [
                        'get_session_info',
                        'mark_item_reviewed',
                        'mark_item_deferred',
                        'mark_item_acted_on',
                        'set_focus',
                        'save_summary',
                        'get_processed_items',
                    ],
                    'description': 'Action to perform',
                },
                'channel_id': {
                    'type': 'string',
                    'description': 'Slack channel ID (for mark_item_* actions)',
                },
                'message_ts': {
                    'type': 'string',
                    'description': 'Message timestamp (for mark_item_* actions)',
                },
                'thread_ts': {
                    'type': 'string',
                    'description': 'Thread timestamp (optional, for mark_item_* actions)',
                },
                'notes': {
                    'type': 'string',
                    'description': 'Notes about the item (optional, for mark_item_* actions)',
                },
                'focus': {
                    'type': 'string',
                    'description': 'Current focus/topic (for set_focus action)',
                },
                'summary_text': {
                    'type': 'string',
                    'description': 'Summary of the conversation (for save_summary action)',
                },
                'key_topics': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'Key topics discussed (for save_summary action)',
                },
                'pending_follow_ups': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'Pending follow-up items (for save_summary action)',
                },
            },
            'required': ['action'],
        }

    async def execute(
        self,
        action: str,
        channel_id: str | None = None,
        message_ts: str | None = None,
        thread_ts: str | None = None,
        notes: str | None = None,
        focus: str | None = None,
        summary_text: str | None = None,
        key_topics: list[str] | None = None,
        pending_follow_ups: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute session management action.

        Args:
            action: Action to perform.
            channel_id: Slack channel ID.
            message_ts: Message timestamp.
            thread_ts: Thread timestamp.
            notes: Notes about the item.
            focus: Current focus/topic.
            summary_text: Summary of the conversation.
            key_topics: Key topics discussed.
            pending_follow_ups: Pending follow-up items.

        Returns:
            Action result.
        """
        if action == 'get_session_info':
            return self._get_session_info()

        elif action == 'mark_item_reviewed':
            return self._mark_item(ItemDisposition.REVIEWED, channel_id, message_ts, thread_ts, notes)

        elif action == 'mark_item_deferred':
            return self._mark_item(ItemDisposition.DEFERRED, channel_id, message_ts, thread_ts, notes)

        elif action == 'mark_item_acted_on':
            return self._mark_item(ItemDisposition.ACTED_ON, channel_id, message_ts, thread_ts, notes)

        elif action == 'set_focus':
            return self._set_focus(focus)

        elif action == 'save_summary':
            return self._save_summary(summary_text, key_topics, pending_follow_ups)

        elif action == 'get_processed_items':
            return self._get_processed_items()

        else:
            return {'error': f'Unknown action: {action}'}

    def _get_session_info(self) -> dict[str, Any]:
        """Get current session information."""
        return {
            'session_id': self._session.session_id,
            'started_at': self._session.started_at,
            'last_activity_at': self._session.last_activity_at,
            'age_hours': round(self._session.get_session_age_hours(), 2),
            'processed_items_count': len(self._session.processed_items),
            'current_focus': self._session.current_focus,
            'has_summary': self._session.conversation_summary is not None,
        }

    def _mark_item(
        self,
        disposition: ItemDisposition,
        channel_id: str | None,
        message_ts: str | None,
        thread_ts: str | None,
        notes: str | None,
    ) -> dict[str, Any]:
        """Mark an item with given disposition."""
        if not channel_id or not message_ts:
            return {'error': 'channel_id and message_ts are required'}

        # Check if already processed
        if self._session.is_item_processed(channel_id, message_ts):
            return {
                'success': True,
                'already_processed': True,
                'channel_id': channel_id,
                'message_ts': message_ts,
            }

        item = self._session.add_processed_item(
            channel_id=channel_id,
            message_ts=message_ts,
            disposition=disposition,
            thread_ts=thread_ts,
            notes=notes,
        )
        self._storage.save(self._session)

        return {
            'success': True,
            'disposition': disposition.value,
            'channel_id': channel_id,
            'message_ts': message_ts,
            'processed_at': item.processed_at,
        }

    def _set_focus(self, focus: str | None) -> dict[str, Any]:
        """Set current focus."""
        self._session.current_focus = focus
        self._session.touch()
        self._storage.save(self._session)

        return {
            'success': True,
            'focus': focus,
        }

    def _save_summary(
        self,
        summary_text: str | None,
        key_topics: list[str] | None,
        pending_follow_ups: list[str] | None,
    ) -> dict[str, Any]:
        """Save conversation summary."""
        if not summary_text:
            return {'error': 'summary_text is required'}

        self._session.conversation_summary = ConversationSummary(
            summary_text=summary_text,
            key_topics=key_topics or [],
            pending_follow_ups=pending_follow_ups or [],
        )
        self._session.touch()
        self._storage.save(self._session)

        return {
            'success': True,
            'summary_saved': True,
            'key_topics': key_topics or [],
            'pending_follow_ups': pending_follow_ups or [],
        }

    def _get_processed_items(self) -> dict[str, Any]:
        """Get list of processed items."""
        items = [
            {
                'channel_id': item.channel_id,
                'message_ts': item.message_ts,
                'thread_ts': item.thread_ts,
                'disposition': item.disposition.value,
                'processed_at': item.processed_at,
                'notes': item.notes,
            }
            for item in self._session.processed_items
        ]

        return {
            'session_id': self._session.session_id,
            'total_items': len(items),
            'items': items,
        }
