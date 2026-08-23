"""Tests for ServerSessionHistory."""

import json
import os
import stat
from datetime import datetime, timedelta
from unittest.mock import patch

from miracast_server.history import _MAX_RECORDS, ServerSessionHistory
from miracast_server.models import ReceiverStats, ServerSessionRecord, SourceInfo


def _make_source_info(name="Test Device", address="AA:BB:CC:DD:EE:FF", model="TestModel"):
    """Helper to create a SourceInfo instance."""
    return SourceInfo(name=name, address=address, model=model)


def _make_stats(duration=60, data_received=1024000):
    """Helper to create a ReceiverStats instance."""
    return ReceiverStats(
        start_time=datetime.now() - timedelta(seconds=duration),
        end_time=datetime.now(),
        duration=duration,
        data_received=data_received,
        average_bitrate=136533.3,
        peak_bitrate=200000.0,
        frames_decoded=1800,
        frames_dropped=2,
        errors=0,
        resolution=(1920, 1080),
        codec="H.264 Baseline",
    )


class TestServerSessionHistoryInit:
    """Test initialization behavior."""

    def test_creates_empty_history_when_no_file_exists(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        assert hist.get_sessions() == []

    def test_creates_parent_directories(self, tmp_path):
        history_file = tmp_path / "subdir" / "nested" / "history.json"
        ServerSessionHistory(history_path=str(history_file))

        assert history_file.parent.exists()

    def test_loads_existing_valid_history(self, tmp_path):
        history_file = tmp_path / "history.json"
        source_info = _make_source_info()
        stats = _make_stats()
        record = ServerSessionRecord(source_info=source_info, stats=stats)
        data = [record.to_dict()]
        history_file.write_text(json.dumps(data))

        hist = ServerSessionHistory(history_path=str(history_file))

        sessions = hist.get_sessions()
        assert len(sessions) == 1
        assert sessions[0].source_info.name == "Test Device"

    def test_invalid_json_initializes_empty(self, tmp_path):
        history_file = tmp_path / "history.json"
        history_file.write_text("{this is not valid json")

        hist = ServerSessionHistory(history_path=str(history_file))

        assert hist.get_sessions() == []

    def test_empty_file_initializes_empty(self, tmp_path):
        history_file = tmp_path / "history.json"
        history_file.write_text("")

        hist = ServerSessionHistory(history_path=str(history_file))

        assert hist.get_sessions() == []

    def test_non_list_json_initializes_empty(self, tmp_path):
        history_file = tmp_path / "history.json"
        history_file.write_text('{"key": "value"}')

        hist = ServerSessionHistory(history_path=str(history_file))

        assert hist.get_sessions() == []

    def test_partially_invalid_records_skipped(self, tmp_path):
        """Valid records are loaded, invalid ones are skipped."""
        history_file = tmp_path / "history.json"
        source_info = _make_source_info()
        stats = _make_stats()
        record = ServerSessionRecord(source_info=source_info, stats=stats)
        valid_entry = record.to_dict()
        invalid_entry = {"source_info": "not a dict"}

        data = [valid_entry, invalid_entry]
        history_file.write_text(json.dumps(data))

        hist = ServerSessionHistory(history_path=str(history_file))

        sessions = hist.get_sessions()
        assert len(sessions) == 1


class TestServerSessionHistoryAddSession:
    """Test adding session records."""

    def test_add_session_creates_record(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        source_info = _make_source_info()
        stats = _make_stats()
        record = hist.add_session(source_info, stats)

        assert isinstance(record, ServerSessionRecord)
        assert record.source_info.name == "Test Device"
        assert record.stats.duration == 60

    def test_add_session_sets_current_timestamp(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        before = datetime.now()
        record = hist.add_session(_make_source_info(), _make_stats())
        after = datetime.now()

        assert before <= record.timestamp <= after

    def test_add_session_persists_to_disk(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        hist.add_session(_make_source_info(), _make_stats())

        # Verify file on disk
        with open(history_file) as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["source_info"]["name"] == "Test Device"

    def test_add_session_appears_in_get_sessions(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        hist.add_session(_make_source_info(), _make_stats())

        sessions = hist.get_sessions()
        assert len(sessions) == 1

    def test_add_multiple_sessions(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        for i in range(5):
            hist.add_session(
                _make_source_info(name=f"Device {i}"),
                _make_stats(),
            )

        sessions = hist.get_sessions()
        assert len(sessions) == 5


class TestServerSessionHistoryMaxRecords:
    """Test the 500 record limit enforcement."""

    def test_enforces_max_500_records(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        # Add 501 records
        for i in range(501):
            hist.add_session(
                _make_source_info(name=f"Device {i}"),
                _make_stats(),
            )

        sessions = hist.get_sessions()
        assert len(sessions) == 500

    def test_discards_oldest_on_overflow(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        # Add 500 records with known timestamps
        base_time = datetime.now() - timedelta(hours=10)
        for i in range(500):
            record = ServerSessionRecord(
                source_info=_make_source_info(name=f"Device {i}"),
                stats=_make_stats(),
                timestamp=base_time + timedelta(seconds=i),
            )
            hist.sessions.append(record)

        # Add one more — this should discard the oldest (Device 0)
        hist.add_session(
            _make_source_info(name="Device 500"),
            _make_stats(),
        )

        sessions = hist.get_sessions()
        assert len(sessions) == 500
        # The oldest (Device 0, timestamp = base_time) should be gone
        names = [s.source_info.name for s in sessions]
        assert "Device 0" not in names
        assert "Device 500" in names

    def test_exactly_500_after_overflow(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        for i in range(600):
            hist.add_session(
                _make_source_info(name=f"Device {i}"),
                _make_stats(),
            )

        assert len(hist.get_sessions()) == _MAX_RECORDS


class TestServerSessionHistorySortOrder:
    """Test that get_sessions returns records sorted by timestamp descending."""

    def test_returns_descending_order(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        base_time = datetime.now() - timedelta(hours=5)
        for i in range(5):
            record = ServerSessionRecord(
                source_info=_make_source_info(name=f"Device {i}"),
                stats=_make_stats(),
                timestamp=base_time + timedelta(minutes=i),
            )
            hist.sessions.append(record)

        sessions = hist.get_sessions()
        # Most recent first
        timestamps = [s.timestamp for s in sessions]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_newest_first(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        old_time = datetime.now() - timedelta(hours=2)
        new_time = datetime.now() - timedelta(minutes=5)

        hist.sessions.append(
            ServerSessionRecord(
                source_info=_make_source_info(name="Old"),
                stats=_make_stats(),
                timestamp=old_time,
            )
        )
        hist.sessions.append(
            ServerSessionRecord(
                source_info=_make_source_info(name="New"),
                stats=_make_stats(),
                timestamp=new_time,
            )
        )

        sessions = hist.get_sessions()
        assert sessions[0].source_info.name == "New"
        assert sessions[1].source_info.name == "Old"

    def test_strictly_descending_with_distinct_timestamps(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        base_time = datetime.now() - timedelta(hours=1)
        for i in range(10):
            record = ServerSessionRecord(
                source_info=_make_source_info(name=f"Device {i}"),
                stats=_make_stats(),
                timestamp=base_time + timedelta(seconds=i * 10),
            )
            hist.sessions.append(record)

        sessions = hist.get_sessions()
        for j in range(len(sessions) - 1):
            assert sessions[j].timestamp > sessions[j + 1].timestamp


class TestServerSessionHistoryFilePermissions:
    """Test that history file is created with 0600 permissions."""

    def test_add_session_creates_file_with_0600(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        hist.add_session(_make_source_info(), _make_stats())

        file_stat = os.stat(history_file)
        mode = stat.S_IMODE(file_stat.st_mode)
        assert mode == 0o600

    def test_clear_creates_file_with_0600(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        hist.add_session(_make_source_info(), _make_stats())
        hist.clear()

        file_stat = os.stat(history_file)
        mode = stat.S_IMODE(file_stat.st_mode)
        assert mode == 0o600


class TestServerSessionHistoryClear:
    """Test clearing history."""

    def test_clear_removes_all_records(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        hist.add_session(_make_source_info(), _make_stats())
        hist.add_session(_make_source_info(name="Device 2"), _make_stats())
        assert len(hist.get_sessions()) == 2

        hist.clear()
        assert hist.get_sessions() == []

    def test_clear_persists_empty_list_to_disk(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        hist.add_session(_make_source_info(), _make_stats())
        hist.clear()

        with open(history_file) as f:
            data = json.load(f)
        assert data == []

    def test_clear_on_write_failure_leaves_state_unchanged(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        hist.add_session(_make_source_info(), _make_stats())
        original_count = len(hist.get_sessions())

        with patch.object(hist, "_write_history", side_effect=OSError("Disk full")):
            hist.clear()

        # State should be unchanged (records restored)
        assert len(hist.get_sessions()) == original_count


class TestServerSessionHistoryDiskWriteFailure:
    """Test behavior when disk writes fail."""

    def test_add_session_retains_in_memory_on_write_failure(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        with patch.object(hist, "_write_history", side_effect=OSError("Disk full")):
            hist.add_session(_make_source_info(), _make_stats())

        # Record should still be in memory
        sessions = hist.get_sessions()
        assert len(sessions) == 1
        assert sessions[0].source_info.name == "Test Device"

    def test_add_session_does_not_raise_on_write_failure(self, tmp_path):
        history_file = tmp_path / "history.json"
        hist = ServerSessionHistory(history_path=str(history_file))

        with patch.object(hist, "_write_history", side_effect=OSError("Disk full")):
            # Should not raise
            record = hist.add_session(_make_source_info(), _make_stats())

        assert record is not None


class TestServerSessionHistoryRoundTrip:
    """Test that data survives write-then-reload cycle."""

    def test_records_survive_reload(self, tmp_path):
        history_file = tmp_path / "history.json"

        # First instance writes records
        hist1 = ServerSessionHistory(history_path=str(history_file))
        hist1.add_session(_make_source_info(name="Alpha"), _make_stats())
        hist1.add_session(_make_source_info(name="Beta"), _make_stats())

        # Second instance reads from same file
        hist2 = ServerSessionHistory(history_path=str(history_file))
        sessions = hist2.get_sessions()

        assert len(sessions) == 2
        names = {s.source_info.name for s in sessions}
        assert "Alpha" in names
        assert "Beta" in names

    def test_clear_then_reload_is_empty(self, tmp_path):
        history_file = tmp_path / "history.json"

        hist1 = ServerSessionHistory(history_path=str(history_file))
        hist1.add_session(_make_source_info(), _make_stats())
        hist1.clear()

        hist2 = ServerSessionHistory(history_path=str(history_file))
        assert hist2.get_sessions() == []
