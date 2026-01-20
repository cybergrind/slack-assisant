"""Session storage using JSON files."""

import json
import logging
from datetime import datetime
from pathlib import Path

from slack_assistant.session.models import SessionState


logger = logging.getLogger(__name__)


class SessionStorage:
    """JSON file storage for session state."""

    # Maximum age in hours before a session is considered stale
    MAX_SESSION_AGE_HOURS = 4.0

    def __init__(self, storage_dir: Path | None = None):
        """Initialize storage.

        Args:
            storage_dir: Directory for storing sessions.
                         Defaults to ~/.slack-assistant/
        """
        if storage_dir is None:
            storage_dir = Path.home() / '.slack-assistant'

        self._storage_dir = storage_dir
        self._session_file = storage_dir / 'session.json'
        self._history_dir = storage_dir / 'session_history'

    def _ensure_dirs(self) -> None:
        """Ensure storage directories exist."""
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._history_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> SessionState | None:
        """Load current session from disk.

        Returns:
            SessionState instance or None if no session exists.
        """
        if not self._session_file.exists():
            return None

        try:
            with open(self._session_file) as f:
                data = json.load(f)
            return SessionState.model_validate(data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f'Failed to load session: {e}')
            return None

    def save(self, session: SessionState) -> None:
        """Save session to disk.

        Args:
            session: Session state to save.
        """
        self._ensure_dirs()
        session.touch()

        with open(self._session_file, 'w') as f:
            json.dump(session.model_dump(), f, indent=2)

        logger.debug(f'Saved session {session.session_id} to {self._session_file}')

    def archive(self, session: SessionState | None = None) -> Path | None:
        """Archive the current session to history.

        Args:
            session: Session to archive, or load current if None.

        Returns:
            Path to archived file, or None if nothing to archive.
        """
        if session is None:
            session = self.load()

        if session is None:
            return None

        self._ensure_dirs()

        # Create archive filename with session ID and date
        date_str = datetime.now().strftime('%Y-%m-%d')
        archive_name = f'session_{session.session_id}_{date_str}.json'
        archive_path = self._history_dir / archive_name

        # Save to archive
        with open(archive_path, 'w') as f:
            json.dump(session.model_dump(), f, indent=2)

        logger.info(f'Archived session {session.session_id} to {archive_path}')

        # Remove current session file
        if self._session_file.exists():
            self._session_file.unlink()

        return archive_path

    def clear(self) -> None:
        """Clear the current session without archiving."""
        if self._session_file.exists():
            self._session_file.unlink()
            logger.debug('Cleared current session')

    def is_session_stale(self, session: SessionState | None = None) -> bool:
        """Check if session is too old to resume.

        Args:
            session: Session to check, or load current if None.

        Returns:
            True if session is older than MAX_SESSION_AGE_HOURS.
        """
        if session is None:
            session = self.load()

        if session is None:
            return True

        return session.get_session_age_hours() > self.MAX_SESSION_AGE_HOURS

    def get_or_create(self, archive_if_stale: bool = True) -> tuple[SessionState, bool]:
        """Get existing session or create new one.

        Args:
            archive_if_stale: If True, archive stale sessions before creating new.

        Returns:
            Tuple of (session, is_resumed) where is_resumed indicates if
            an existing session was loaded.
        """
        existing = self.load()

        if existing is not None:
            if self.is_session_stale(existing):
                if archive_if_stale:
                    self.archive(existing)
                # Create new session
                new_session = SessionState()
                self.save(new_session)
                return new_session, False
            else:
                # Resume existing session
                return existing, True

        # No existing session, create new
        new_session = SessionState()
        self.save(new_session)
        return new_session, False

    def list_archived(self, limit: int = 10) -> list[Path]:
        """List archived session files.

        Args:
            limit: Maximum number of files to return.

        Returns:
            List of archive file paths, newest first.
        """
        if not self._history_dir.exists():
            return []

        files = list(self._history_dir.glob('session_*.json'))
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files[:limit]

    def load_archived(self, archive_path: Path) -> SessionState | None:
        """Load an archived session.

        Args:
            archive_path: Path to archived session file.

        Returns:
            SessionState or None if load fails.
        """
        if not archive_path.exists():
            return None

        try:
            with open(archive_path) as f:
                data = json.load(f)
            return SessionState.model_validate(data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f'Failed to load archived session: {e}')
            return None

    def restore_from_archive(self, archive_path: Path) -> SessionState | None:
        """Restore an archived session as the current session.

        Args:
            archive_path: Path to archived session to restore.

        Returns:
            The restored session, or None if restore fails.
        """
        session = self.load_archived(archive_path)
        if session is None:
            return None

        # Archive current session first if it exists
        current = self.load()
        if current is not None:
            self.archive(current)

        # Save the restored session as current
        self.save(session)
        return session
