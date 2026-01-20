"""Tests for emoji pattern functionality."""

from pathlib import Path

import pytest

from slack_assistant.preferences import EmojiPattern, PreferenceStorage, UserPreferences


class TestEmojiPattern:
    """Tests for emoji pattern model."""

    def test_emoji_pattern_creation(self):
        """Test creating an emoji pattern."""
        pattern = EmojiPattern(
            emoji='eyes',
            meaning='acknowledged',
            marks_as_handled=True,
            priority_adjustment=-1,
        )

        assert pattern.emoji == 'eyes'
        assert pattern.meaning == 'acknowledged'
        assert pattern.marks_as_handled is True
        assert pattern.priority_adjustment == -1
        assert pattern.id is not None

    def test_emoji_pattern_defaults(self):
        """Test emoji pattern default values."""
        pattern = EmojiPattern(emoji='thumbsup', meaning='approved')

        assert pattern.marks_as_handled is False
        assert pattern.priority_adjustment == 0


class TestUserPreferencesEmojiPatterns:
    """Tests for emoji patterns in user preferences."""

    def test_get_emoji_patterns_text_empty(self):
        """Test getting emoji patterns text when empty."""
        prefs = UserPreferences()
        assert prefs.get_emoji_patterns_text() == 'No emoji patterns defined.'

    def test_get_emoji_patterns_text_with_patterns(self):
        """Test getting emoji patterns text with patterns."""
        prefs = UserPreferences(
            emoji_patterns=[
                EmojiPattern(emoji='eyes', meaning='seen', marks_as_handled=True),
                EmojiPattern(emoji='thumbsup', meaning='approved'),
            ]
        )

        text = prefs.get_emoji_patterns_text()
        assert 'emoji communication patterns' in text
        assert ':eyes: means "seen" (marks as handled)' in text
        assert ':thumbsup: means "approved"' in text
        assert '(marks as handled)' not in text.split('\n')[-1]  # thumbsup doesn't mark

    def test_get_acknowledgment_emojis_empty(self):
        """Test getting acknowledgment emojis when none defined."""
        prefs = UserPreferences()
        assert prefs.get_acknowledgment_emojis() == []

    def test_get_acknowledgment_emojis_filtered(self):
        """Test getting only emojis that mark as handled."""
        prefs = UserPreferences(
            emoji_patterns=[
                EmojiPattern(emoji='eyes', meaning='seen', marks_as_handled=True),
                EmojiPattern(emoji='thumbsup', meaning='approved', marks_as_handled=False),
                EmojiPattern(emoji='white_check_mark', meaning='done', marks_as_handled=True),
            ]
        )

        emojis = prefs.get_acknowledgment_emojis()
        assert 'eyes' in emojis
        assert 'white_check_mark' in emojis
        assert 'thumbsup' not in emojis

    def test_get_emoji_pattern_by_name(self):
        """Test finding emoji pattern by name."""
        pattern = EmojiPattern(emoji='eyes', meaning='seen')
        prefs = UserPreferences(emoji_patterns=[pattern])

        found = prefs.get_emoji_pattern('eyes')
        assert found is not None
        assert found.emoji == 'eyes'

        not_found = prefs.get_emoji_pattern('nonexistent')
        assert not_found is None


class TestPreferenceStorageEmojiPatterns:
    """Tests for emoji pattern storage."""

    @pytest.fixture
    def tmp_storage(self, tmp_path: Path) -> PreferenceStorage:
        """Create a storage instance with temp directory."""
        return PreferenceStorage(storage_dir=tmp_path)

    def test_save_and_load_emoji_patterns(self, tmp_storage: PreferenceStorage):
        """Test saving and loading emoji patterns."""
        prefs = UserPreferences(
            emoji_patterns=[
                EmojiPattern(emoji='eyes', meaning='seen', marks_as_handled=True),
            ]
        )

        tmp_storage.save(prefs)
        loaded = tmp_storage.load()

        assert len(loaded.emoji_patterns) == 1
        assert loaded.emoji_patterns[0].emoji == 'eyes'
        assert loaded.emoji_patterns[0].marks_as_handled is True

    def test_emoji_pattern_persistence(self, tmp_storage: PreferenceStorage):
        """Test that emoji patterns persist across load/save cycles."""
        # Add an emoji pattern
        prefs = tmp_storage.load()
        prefs.emoji_patterns.append(EmojiPattern(id='test123', emoji='rocket', meaning='shipped'))
        tmp_storage.save(prefs)

        # Load again and verify
        loaded = tmp_storage.load()
        pattern = loaded.get_emoji_pattern('rocket')

        assert pattern is not None
        assert pattern.id == 'test123'
        assert pattern.meaning == 'shipped'
