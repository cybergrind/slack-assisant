"""Tests for session management."""

from pathlib import Path

import pytest

from slack_assistant.session import (
    AnalyzedItem,
    ConversationSummary,
    ItemDisposition,
    ProcessedItem,
    SessionState,
    SessionStorage,
)


class TestSessionModels:
    """Tests for session models."""

    def test_processed_item_key(self):
        """Test processed item key generation."""
        item = ProcessedItem(
            channel_id='C123',
            message_ts='1234.5678',
            disposition=ItemDisposition.REVIEWED,
        )
        assert item.key == 'C123:1234.5678'

    def test_session_state_add_processed_item(self):
        """Test adding processed items to session."""
        session = SessionState()
        assert len(session.processed_items) == 0

        item = session.add_processed_item(
            channel_id='C123',
            message_ts='1234.5678',
            disposition=ItemDisposition.REVIEWED,
            notes='Test note',
        )

        assert len(session.processed_items) == 1
        assert item.channel_id == 'C123'
        assert item.message_ts == '1234.5678'
        assert item.disposition == ItemDisposition.REVIEWED
        assert item.notes == 'Test note'

    def test_session_state_is_item_processed(self):
        """Test checking if item is processed."""
        session = SessionState()
        session.add_processed_item('C123', '1234.5678', ItemDisposition.REVIEWED)

        assert session.is_item_processed('C123', '1234.5678') is True
        assert session.is_item_processed('C123', '9999.9999') is False
        assert session.is_item_processed('C456', '1234.5678') is False

    def test_session_state_get_processed_keys(self):
        """Test getting processed item keys."""
        session = SessionState()
        session.add_processed_item('C123', '1111.1111', ItemDisposition.REVIEWED)
        session.add_processed_item('C456', '2222.2222', ItemDisposition.DEFERRED)

        keys = session.get_processed_keys()
        assert keys == {'C123:1111.1111', 'C456:2222.2222'}

    def test_session_state_touch(self):
        """Test touching session updates last_activity_at."""
        session = SessionState()
        original_activity = session.last_activity_at

        # Ensure some time passes
        import time

        time.sleep(0.01)
        session.touch()

        assert session.last_activity_at > original_activity

    def test_session_state_get_session_age_hours(self):
        """Test calculating session age."""
        session = SessionState()
        # Age should be very small for newly created session
        assert session.get_session_age_hours() < 0.1

    def test_conversation_summary_creation(self):
        """Test conversation summary creation."""
        summary = ConversationSummary(
            summary_text='Discussed project status',
            key_topics=['deadlines', 'blockers'],
            pending_follow_ups=['Review PR #123', 'Reply to John'],
        )

        assert summary.summary_text == 'Discussed project status'
        assert len(summary.key_topics) == 2
        assert len(summary.pending_follow_ups) == 2


class TestSessionStorage:
    """Tests for session storage."""

    @pytest.fixture
    def tmp_storage(self, tmp_path: Path) -> SessionStorage:
        """Create a storage instance with temp directory."""
        return SessionStorage(storage_dir=tmp_path)

    def test_load_nonexistent_returns_none(self, tmp_storage: SessionStorage):
        """Test loading when no session exists."""
        session = tmp_storage.load()
        assert session is None

    def test_save_and_load(self, tmp_storage: SessionStorage):
        """Test saving and loading a session."""
        session = SessionState(session_id='test123')
        session.add_processed_item('C123', '1234.5678', ItemDisposition.REVIEWED)

        tmp_storage.save(session)
        loaded = tmp_storage.load()

        assert loaded is not None
        assert loaded.session_id == 'test123'
        assert len(loaded.processed_items) == 1

    def test_get_or_create_new(self, tmp_storage: SessionStorage):
        """Test get_or_create creates new session when none exists."""
        session, is_resumed = tmp_storage.get_or_create()

        assert session is not None
        assert is_resumed is False

    def test_get_or_create_resume(self, tmp_storage: SessionStorage):
        """Test get_or_create resumes existing session."""
        # Create and save a session first
        original = SessionState(session_id='original')
        tmp_storage.save(original)

        session, is_resumed = tmp_storage.get_or_create()

        assert session.session_id == 'original'
        assert is_resumed is True

    def test_is_session_stale_fresh(self, tmp_storage: SessionStorage):
        """Test fresh session is not stale."""
        session = SessionState()
        tmp_storage.save(session)

        assert tmp_storage.is_session_stale() is False

    def test_archive_session(self, tmp_storage: SessionStorage):
        """Test archiving a session."""
        session = SessionState(session_id='archive_me')
        tmp_storage.save(session)

        archive_path = tmp_storage.archive()

        assert archive_path is not None
        assert archive_path.exists()
        assert 'archive_me' in archive_path.name

        # Current session should be cleared
        assert tmp_storage.load() is None

    def test_clear_session(self, tmp_storage: SessionStorage):
        """Test clearing current session."""
        session = SessionState()
        tmp_storage.save(session)

        tmp_storage.clear()

        assert tmp_storage.load() is None

    def test_list_archived(self, tmp_storage: SessionStorage):
        """Test listing archived sessions."""
        # Create and archive a few sessions
        for i in range(3):
            session = SessionState(session_id=f'session_{i}')
            tmp_storage.save(session)
            tmp_storage.archive()

        archives = tmp_storage.list_archived()
        assert len(archives) == 3


class TestItemDisposition:
    """Tests for item disposition enum."""

    def test_disposition_values(self):
        """Test disposition enum values."""
        assert ItemDisposition.REVIEWED.value == 'reviewed'
        assert ItemDisposition.DEFERRED.value == 'deferred'
        assert ItemDisposition.ACTED_ON.value == 'acted_on'

    def test_disposition_comparison(self):
        """Test disposition enum comparison."""
        assert ItemDisposition.REVIEWED == ItemDisposition.REVIEWED
        assert ItemDisposition.REVIEWED != ItemDisposition.DEFERRED


class TestAnalyzedItem:
    """Tests for AnalyzedItem model."""

    def test_analyzed_item_key(self):
        """Test analyzed item key generation."""
        item = AnalyzedItem(
            channel_id='C123',
            message_ts='1234.5678',
            priority='HIGH',
            summary='Test summary',
        )
        assert item.key == 'C123:1234.5678'

    def test_analyzed_item_with_optional_fields(self):
        """Test analyzed item with all optional fields."""
        item = AnalyzedItem(
            channel_id='C123',
            message_ts='1234.5678',
            thread_ts='1234.0000',
            priority='CRITICAL',
            summary='Urgent request',
            action_needed='Reply with approval',
            context_notes='Related to project X',
        )
        assert item.thread_ts == '1234.0000'
        assert item.action_needed == 'Reply with approval'
        assert item.context_notes == 'Related to project X'
        assert item.analyzed_at is not None

    def test_analyzed_item_defaults(self):
        """Test analyzed item default values."""
        item = AnalyzedItem(
            channel_id='C123',
            message_ts='1234.5678',
            priority='LOW',
            summary='General chat',
        )
        assert item.thread_ts is None
        assert item.action_needed is None
        assert item.context_notes is None


class TestSessionStateAnalyzedItems:
    """Tests for SessionState analyzed item methods."""

    def test_add_analyzed_item(self):
        """Test adding analyzed items to session."""
        session = SessionState()
        assert len(session.analyzed_items) == 0

        item = session.add_analyzed_item(
            channel_id='C123',
            message_ts='1234.5678',
            priority='HIGH',
            summary='Test message',
            action_needed='Reply needed',
        )

        assert len(session.analyzed_items) == 1
        assert item.channel_id == 'C123'
        assert item.message_ts == '1234.5678'
        assert item.priority == 'HIGH'
        assert item.summary == 'Test message'
        assert item.action_needed == 'Reply needed'

    def test_add_analyzed_item_upserts(self):
        """Test that adding analyzed item with same key upserts."""
        session = SessionState()

        # Add first item
        session.add_analyzed_item(
            channel_id='C123',
            message_ts='1234.5678',
            priority='MEDIUM',
            summary='First analysis',
        )
        assert len(session.analyzed_items) == 1
        assert session.analyzed_items[0].priority == 'MEDIUM'

        # Add item with same key - should replace
        session.add_analyzed_item(
            channel_id='C123',
            message_ts='1234.5678',
            priority='CRITICAL',
            summary='Updated analysis',
        )
        assert len(session.analyzed_items) == 1
        assert session.analyzed_items[0].priority == 'CRITICAL'
        assert session.analyzed_items[0].summary == 'Updated analysis'

    def test_get_analyzed_item_found(self):
        """Test getting an existing analyzed item."""
        session = SessionState()
        session.add_analyzed_item(
            channel_id='C123',
            message_ts='1234.5678',
            priority='HIGH',
            summary='Test',
        )

        item = session.get_analyzed_item('C123', '1234.5678')
        assert item is not None
        assert item.priority == 'HIGH'

    def test_get_analyzed_item_not_found(self):
        """Test getting a non-existent analyzed item."""
        session = SessionState()
        item = session.get_analyzed_item('C123', '9999.9999')
        assert item is None

    def test_get_analyzed_keys(self):
        """Test getting analyzed item keys."""
        session = SessionState()
        session.add_analyzed_item('C123', '1111.1111', 'HIGH', 'Summary 1')
        session.add_analyzed_item('C456', '2222.2222', 'LOW', 'Summary 2')

        keys = session.get_analyzed_keys()
        assert keys == {'C123:1111.1111', 'C456:2222.2222'}

    def test_get_analyzed_keys_empty(self):
        """Test getting analyzed keys when empty."""
        session = SessionState()
        keys = session.get_analyzed_keys()
        assert keys == set()

    def test_session_summary_includes_analyzed_count(self):
        """Test that session summary includes analyzed items count."""
        session = SessionState()
        session.add_analyzed_item('C123', '1111.1111', 'HIGH', 'Summary 1')
        session.add_analyzed_item('C456', '2222.2222', 'LOW', 'Summary 2')

        summary = session.get_summary_text()
        assert 'Items analyzed: 2' in summary
