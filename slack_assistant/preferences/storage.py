"""Preference storage using JSON files."""

import json
import logging
from pathlib import Path

from slack_assistant.preferences.models import UserPreferences


logger = logging.getLogger(__name__)


class PreferenceStorage:
    """JSON file storage for user preferences."""

    def __init__(self, storage_dir: Path | None = None):
        """Initialize storage.

        Args:
            storage_dir: Directory for storing preferences.
                         Defaults to ~/.slack-assistant/
        """
        if storage_dir is None:
            storage_dir = Path.home() / '.slack-assistant'

        self._storage_dir = storage_dir
        self._prefs_file = storage_dir / 'preferences.json'

    def _ensure_dir(self) -> None:
        """Ensure storage directory exists."""
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> UserPreferences:
        """Load preferences from disk.

        Returns:
            UserPreferences instance.
        """
        if not self._prefs_file.exists():
            return UserPreferences()

        try:
            with open(self._prefs_file) as f:
                data = json.load(f)
            return UserPreferences.model_validate(data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f'Failed to load preferences: {e}')
            return UserPreferences()

    def save(self, prefs: UserPreferences) -> None:
        """Save preferences to disk.

        Args:
            prefs: Preferences to save.
        """
        self._ensure_dir()

        with open(self._prefs_file, 'w') as f:
            json.dump(prefs.model_dump(), f, indent=2)

        logger.debug(f'Saved preferences to {self._prefs_file}')
