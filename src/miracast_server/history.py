"""Session history management for Ubuntu Miracast Server."""

import json
import logging
import os
import stat
from datetime import datetime
from pathlib import Path

from miracast_server.models import ReceiverStats, ServerSessionRecord, SourceInfo

logger = logging.getLogger(__name__)

# Maximum number of session records to retain
_MAX_RECORDS = 500


class ServerSessionHistory:
    """Manages persistence of server session records.

    Stores session records in a JSON file with 0600 permissions.
    Enforces a maximum of 500 records, discarding the oldest when the limit
    is exceeded. Returns sessions sorted by timestamp in descending order.

    On disk write failure, records are retained in memory and a persist-error
    is logged.
    """

    def __init__(self, history_path: str | None = None):
        """Initialize the session history manager.

        Args:
            history_path: Optional path to the history file. If not provided,
                          defaults to ~/.local/share/ubuntu-miracast-server/history.json.
        """
        if history_path:
            self.history_path = Path(history_path)
        else:
            self.history_path = (
                Path.home() / ".local" / "share" / "ubuntu-miracast-server" / "history.json"
            )

        # Create directory if it doesn't exist
        self.history_path.parent.mkdir(parents=True, exist_ok=True)

        # Load history from disk
        self.sessions: list[ServerSessionRecord] = self._load_history()

    def _load_history(self) -> list[ServerSessionRecord]:
        """Load session history from file.

        Returns an empty list if the file does not exist, is empty,
        or contains invalid JSON.
        """
        if not self.history_path.exists():
            return []

        try:
            with open(self.history_path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            logger.warning(
                "Failed to load history from %s: %s — starting with empty history",
                self.history_path,
                e,
            )
            return []

        if not isinstance(data, list):
            logger.warning(
                "History file %s does not contain a JSON array — starting with empty history",
                self.history_path,
            )
            return []

        sessions: list[ServerSessionRecord] = []
        for entry in data:
            try:
                record = ServerSessionRecord.from_dict(entry)
                sessions.append(record)
            except (ValueError, TypeError, KeyError) as e:
                logger.error("Failed to deserialize session record: %s", e)

        logger.info("Loaded %d session records from history", len(sessions))
        return sessions

    def _save_history(self) -> None:
        """Persist session history to disk with 0600 permissions.

        On failure, logs an error (persist-error) but does not raise.
        Records remain in memory regardless of disk outcome.
        """
        try:
            self._write_history()
        except OSError as e:
            logger.error("persist-error: Failed to save history to %s: %s", self.history_path, e)

    def _write_history(self) -> None:
        """Write history to disk with 0600 permissions using atomic write.

        Raises:
            OSError: If writing fails.
        """
        # Ensure parent directory exists
        self.history_path.parent.mkdir(parents=True, exist_ok=True)

        data = [record.to_dict() for record in self.sessions]

        # Write to a temporary file then rename for atomicity
        tmp_path = self.history_path.with_suffix(".tmp")
        try:
            fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(data, f, indent=2)
            except Exception:
                raise
            # Rename atomically
            tmp_path.rename(self.history_path)
        except Exception:
            # Clean up temp file on failure
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise

        # Ensure final file has correct permissions
        try:
            os.chmod(str(self.history_path), stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def add_session(
        self, source_info: SourceInfo, stats: ReceiverStats
    ) -> ServerSessionRecord:
        """Add a new session record.

        Creates a ServerSessionRecord with the current timestamp, appends it
        to the in-memory list, enforces the 500 record limit (discarding
        oldest), and persists to disk.

        Args:
            source_info: Information about the Miracast source device.
            stats: Statistics from the receiving session.

        Returns:
            The created ServerSessionRecord.
        """
        record = ServerSessionRecord(
            source_info=source_info,
            stats=stats,
            timestamp=datetime.now(),
        )

        self.sessions.append(record)

        # Enforce maximum record limit — discard oldest
        if len(self.sessions) > _MAX_RECORDS:
            # Sort by timestamp ascending so we can trim the oldest
            self.sessions.sort(key=lambda r: r.timestamp)
            self.sessions = self.sessions[-_MAX_RECORDS:]

        self._save_history()

        logger.info(
            "Added session record: %s (%s)",
            source_info.name,
            source_info.address,
        )
        return record

    def get_sessions(self) -> list[ServerSessionRecord]:
        """Get all session records sorted by timestamp descending.

        Returns:
            List of ServerSessionRecord objects, most recent first.
        """
        return sorted(self.sessions, key=lambda r: r.timestamp, reverse=True)

    def clear(self) -> None:
        """Clear all session records.

        Removes all records from memory and persists an empty list to disk.
        If the disk write fails, logs a persist-error and leaves the history
        state unchanged (records remain in memory).
        """
        previous_sessions = self.sessions[:]
        self.sessions = []

        try:
            self._write_history()
        except OSError as e:
            logger.error(
                "persist-error: Failed to clear history file %s: %s", self.history_path, e
            )
            # Restore previous state on failure
            self.sessions = previous_sessions
            return

        logger.info("Session history cleared")
