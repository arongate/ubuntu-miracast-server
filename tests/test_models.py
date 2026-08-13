"""Tests for IncomingConnection data model validation."""

import pytest
from datetime import datetime, timedelta

from miracast_server.models import IncomingConnection


class TestIncomingConnectionValidMAC:
    """Test MAC address validation for peer_address."""

    def test_valid_mac_lowercase(self):
        conn = IncomingConnection(
            peer_address="aa:bb:cc:dd:ee:ff",
            peer_ip="192.168.1.1",
            peer_name="Test Device",
            group_interface="p2p-wlo1-0",
            our_ip="192.168.1.2",
            connected_at=datetime.now(),
        )
        assert conn.peer_address == "aa:bb:cc:dd:ee:ff"

    def test_valid_mac_uppercase(self):
        conn = IncomingConnection(
            peer_address="AA:BB:CC:DD:EE:FF",
            peer_ip="192.168.1.1",
            peer_name="Test Device",
            group_interface="p2p-wlo1-0",
            our_ip="192.168.1.2",
            connected_at=datetime.now(),
        )
        assert conn.peer_address == "AA:BB:CC:DD:EE:FF"

    def test_valid_mac_mixed_case(self):
        conn = IncomingConnection(
            peer_address="aA:Bb:cC:Dd:eE:fF",
            peer_ip="192.168.1.1",
            peer_name="Test Device",
            group_interface="p2p-wlo1-0",
            our_ip="192.168.1.2",
            connected_at=datetime.now(),
        )
        assert conn.peer_address == "aA:Bb:cC:Dd:eE:fF"

    def test_invalid_mac_too_short(self):
        with pytest.raises(ValueError, match="peer_address"):
            IncomingConnection(
                peer_address="AA:BB:CC:DD:EE",
                peer_ip="192.168.1.1",
                peer_name="Test Device",
                group_interface="p2p-wlo1-0",
                our_ip="192.168.1.2",
                connected_at=datetime.now(),
            )

    def test_invalid_mac_non_hex(self):
        with pytest.raises(ValueError, match="peer_address"):
            IncomingConnection(
                peer_address="GG:HH:II:JJ:KK:LL",
                peer_ip="192.168.1.1",
                peer_name="Test Device",
                group_interface="p2p-wlo1-0",
                our_ip="192.168.1.2",
                connected_at=datetime.now(),
            )

    def test_invalid_mac_missing_colons(self):
        with pytest.raises(ValueError, match="peer_address"):
            IncomingConnection(
                peer_address="AABBCCDDEEFF",
                peer_ip="192.168.1.1",
                peer_name="Test Device",
                group_interface="p2p-wlo1-0",
                our_ip="192.168.1.2",
                connected_at=datetime.now(),
            )

    def test_invalid_mac_empty(self):
        with pytest.raises(ValueError, match="peer_address"):
            IncomingConnection(
                peer_address="",
                peer_ip="192.168.1.1",
                peer_name="Test Device",
                group_interface="p2p-wlo1-0",
                our_ip="192.168.1.2",
                connected_at=datetime.now(),
            )


class TestIncomingConnectionValidIPv4:
    """Test IPv4 address validation for peer_ip and our_ip."""

    def test_valid_ip(self):
        conn = IncomingConnection(
            peer_address="AA:BB:CC:DD:EE:FF",
            peer_ip="192.168.1.1",
            peer_name="Test Device",
            group_interface="p2p-wlo1-0",
            our_ip="10.0.0.1",
            connected_at=datetime.now(),
        )
        assert conn.peer_ip == "192.168.1.1"
        assert conn.our_ip == "10.0.0.1"

    def test_valid_ip_zero(self):
        conn = IncomingConnection(
            peer_address="AA:BB:CC:DD:EE:FF",
            peer_ip="0.0.0.0",
            peer_name="Test Device",
            group_interface="p2p-wlo1-0",
            our_ip="255.255.255.255",
            connected_at=datetime.now(),
        )
        assert conn.peer_ip == "0.0.0.0"
        assert conn.our_ip == "255.255.255.255"

    def test_invalid_ip_octet_too_high(self):
        with pytest.raises(ValueError, match="peer_ip"):
            IncomingConnection(
                peer_address="AA:BB:CC:DD:EE:FF",
                peer_ip="256.1.1.1",
                peer_name="Test Device",
                group_interface="p2p-wlo1-0",
                our_ip="192.168.1.2",
                connected_at=datetime.now(),
            )

    def test_invalid_ip_leading_zeros(self):
        with pytest.raises(ValueError, match="peer_ip"):
            IncomingConnection(
                peer_address="AA:BB:CC:DD:EE:FF",
                peer_ip="192.168.01.1",
                peer_name="Test Device",
                group_interface="p2p-wlo1-0",
                our_ip="192.168.1.2",
                connected_at=datetime.now(),
            )

    def test_invalid_ip_too_few_octets(self):
        with pytest.raises(ValueError, match="peer_ip"):
            IncomingConnection(
                peer_address="AA:BB:CC:DD:EE:FF",
                peer_ip="192.168.1",
                peer_name="Test Device",
                group_interface="p2p-wlo1-0",
                our_ip="192.168.1.2",
                connected_at=datetime.now(),
            )

    def test_invalid_ip_non_numeric(self):
        with pytest.raises(ValueError, match="peer_ip"):
            IncomingConnection(
                peer_address="AA:BB:CC:DD:EE:FF",
                peer_ip="abc.def.ghi.jkl",
                peer_name="Test Device",
                group_interface="p2p-wlo1-0",
                our_ip="192.168.1.2",
                connected_at=datetime.now(),
            )

    def test_invalid_our_ip(self):
        with pytest.raises(ValueError, match="our_ip"):
            IncomingConnection(
                peer_address="AA:BB:CC:DD:EE:FF",
                peer_ip="192.168.1.1",
                peer_name="Test Device",
                group_interface="p2p-wlo1-0",
                our_ip="999.999.999.999",
                connected_at=datetime.now(),
            )


class TestIncomingConnectionGroupInterface:
    """Test group_interface validation."""

    def test_valid_interface_min_length(self):
        conn = IncomingConnection(
            peer_address="AA:BB:CC:DD:EE:FF",
            peer_ip="192.168.1.1",
            peer_name="Test Device",
            group_interface="p2",
            our_ip="192.168.1.2",
            connected_at=datetime.now(),
        )
        assert conn.group_interface == "p2"

    def test_valid_interface_max_length(self):
        conn = IncomingConnection(
            peer_address="AA:BB:CC:DD:EE:FF",
            peer_ip="192.168.1.1",
            peer_name="Test Device",
            group_interface="p2p-wlo1-0123456",  # 16 characters
            our_ip="192.168.1.2",
            connected_at=datetime.now(),
        )
        assert conn.group_interface == "p2p-wlo1-0123456"

    def test_invalid_interface_too_short(self):
        with pytest.raises(ValueError, match="group_interface"):
            IncomingConnection(
                peer_address="AA:BB:CC:DD:EE:FF",
                peer_ip="192.168.1.1",
                peer_name="Test Device",
                group_interface="p",
                our_ip="192.168.1.2",
                connected_at=datetime.now(),
            )

    def test_invalid_interface_too_long(self):
        with pytest.raises(ValueError, match="group_interface"):
            IncomingConnection(
                peer_address="AA:BB:CC:DD:EE:FF",
                peer_ip="192.168.1.1",
                peer_name="Test Device",
                group_interface="p2p-wlo1-01234567",  # 17 characters
                our_ip="192.168.1.2",
                connected_at=datetime.now(),
            )

    def test_invalid_interface_empty(self):
        with pytest.raises(ValueError, match="group_interface"):
            IncomingConnection(
                peer_address="AA:BB:CC:DD:EE:FF",
                peer_ip="192.168.1.1",
                peer_name="Test Device",
                group_interface="",
                our_ip="192.168.1.2",
                connected_at=datetime.now(),
            )


class TestIncomingConnectionConnectedAt:
    """Test connected_at validation (not in the future)."""

    def test_valid_past_time(self):
        past = datetime.now() - timedelta(hours=1)
        conn = IncomingConnection(
            peer_address="AA:BB:CC:DD:EE:FF",
            peer_ip="192.168.1.1",
            peer_name="Test Device",
            group_interface="p2p-wlo1-0",
            our_ip="192.168.1.2",
            connected_at=past,
        )
        assert conn.connected_at == past

    def test_valid_now(self):
        now = datetime.now()
        conn = IncomingConnection(
            peer_address="AA:BB:CC:DD:EE:FF",
            peer_ip="192.168.1.1",
            peer_name="Test Device",
            group_interface="p2p-wlo1-0",
            our_ip="192.168.1.2",
            connected_at=now,
        )
        assert conn.connected_at == now

    def test_invalid_future_time(self):
        future = datetime.now() + timedelta(hours=1)
        with pytest.raises(ValueError, match="connected_at"):
            IncomingConnection(
                peer_address="AA:BB:CC:DD:EE:FF",
                peer_ip="192.168.1.1",
                peer_name="Test Device",
                group_interface="p2p-wlo1-0",
                our_ip="192.168.1.2",
                connected_at=future,
            )


class TestIncomingConnectionGoRole:
    """Test go_role default and behavior."""

    def test_default_go_role_true(self):
        conn = IncomingConnection(
            peer_address="AA:BB:CC:DD:EE:FF",
            peer_ip="192.168.1.1",
            peer_name="Test Device",
            group_interface="p2p-wlo1-0",
            our_ip="192.168.1.2",
            connected_at=datetime.now(),
        )
        assert conn.go_role is True

    def test_explicit_go_role_false(self):
        conn = IncomingConnection(
            peer_address="AA:BB:CC:DD:EE:FF",
            peer_ip="192.168.1.1",
            peer_name="Test Device",
            group_interface="p2p-wlo1-0",
            our_ip="192.168.1.2",
            connected_at=datetime.now(),
            go_role=False,
        )
        assert conn.go_role is False


class TestIncomingConnectionPeerName:
    """Test peer_name has no validation beyond being a string."""

    def test_empty_peer_name(self):
        conn = IncomingConnection(
            peer_address="AA:BB:CC:DD:EE:FF",
            peer_ip="192.168.1.1",
            peer_name="",
            group_interface="p2p-wlo1-0",
            our_ip="192.168.1.2",
            connected_at=datetime.now(),
        )
        assert conn.peer_name == ""

    def test_long_peer_name(self):
        name = "A very long device name with special chars: 日本語 & emoji 🎉"
        conn = IncomingConnection(
            peer_address="AA:BB:CC:DD:EE:FF",
            peer_ip="192.168.1.1",
            peer_name=name,
            group_interface="p2p-wlo1-0",
            our_ip="192.168.1.2",
            connected_at=datetime.now(),
        )
        assert conn.peer_name == name



# ============================================================================
# Tests for ReceiverStats, SourceInfo, and ServerSessionRecord (Task 2.2)
# ============================================================================

from miracast_server.models import ReceiverStats, SourceInfo, ServerSessionRecord


class TestReceiverStatsValidation:
    """Test ReceiverStats validation rules."""

    def test_valid_defaults(self):
        stats = ReceiverStats()
        assert stats.duration == 0
        assert stats.data_received == 0
        assert stats.frames_decoded == 0
        assert stats.frames_dropped == 0

    def test_valid_all_fields(self):
        now = datetime.now()
        stats = ReceiverStats(
            start_time=now,
            end_time=now + timedelta(minutes=5),
            duration=300,
            data_received=1024000,
            average_bitrate=5000.0,
            peak_bitrate=8000.0,
            frames_decoded=9000,
            frames_dropped=10,
            errors=2,
            resolution=(1920, 1080),
            codec="H.264 Baseline",
        )
        assert stats.duration == 300
        assert stats.data_received == 1024000
        assert stats.frames_decoded == 9000
        assert stats.frames_dropped == 10

    def test_invalid_negative_duration(self):
        with pytest.raises(ValueError, match="duration"):
            ReceiverStats(duration=-1)

    def test_invalid_negative_data_received(self):
        with pytest.raises(ValueError, match="data_received"):
            ReceiverStats(data_received=-1)

    def test_invalid_frames_decoded_less_than_dropped(self):
        with pytest.raises(ValueError, match="frames_decoded"):
            ReceiverStats(frames_decoded=5, frames_dropped=10)

    def test_valid_frames_decoded_equals_dropped(self):
        stats = ReceiverStats(frames_decoded=10, frames_dropped=10)
        assert stats.frames_decoded == 10
        assert stats.frames_dropped == 10

    def test_valid_zero_frames(self):
        stats = ReceiverStats(frames_decoded=0, frames_dropped=0)
        assert stats.frames_decoded == 0
        assert stats.frames_dropped == 0

    def test_invalid_negative_frames_decoded(self):
        with pytest.raises(ValueError, match="frames_decoded"):
            ReceiverStats(frames_decoded=-1, frames_dropped=0)

    def test_invalid_negative_frames_dropped(self):
        with pytest.raises(ValueError, match="frames_dropped"):
            ReceiverStats(frames_decoded=0, frames_dropped=-1)

    def test_end_time_none_allowed(self):
        stats = ReceiverStats(end_time=None)
        assert stats.end_time is None


class TestSourceInfo:
    """Test SourceInfo dataclass."""

    def test_required_fields(self):
        info = SourceInfo(name="My Phone", address="AA:BB:CC:DD:EE:FF", model="Pixel 8")
        assert info.name == "My Phone"
        assert info.address == "AA:BB:CC:DD:EE:FF"
        assert info.model == "Pixel 8"

    def test_default_optional_fields(self):
        info = SourceInfo(name="Test", address="11:22:33:44:55:66", model="Model X")
        assert info.resolution == (0, 0)
        assert info.codec == ""
        assert info.audio_codec == ""

    def test_all_fields(self):
        info = SourceInfo(
            name="Living Room TV",
            address="AA:BB:CC:DD:EE:FF",
            model="Samsung Galaxy S24",
            resolution=(1920, 1080),
            codec="H.264 Baseline",
            audio_codec="AAC-LC",
        )
        assert info.resolution == (1920, 1080)
        assert info.codec == "H.264 Baseline"
        assert info.audio_codec == "AAC-LC"


class TestServerSessionRecordToDict:
    """Test ServerSessionRecord.to_dict serialization."""

    def _make_record(self, end_time=None):
        now = datetime(2024, 6, 15, 10, 30, 0)
        source = SourceInfo(
            name="Test Device",
            address="AA:BB:CC:DD:EE:FF",
            model="Test Model",
            resolution=(1920, 1080),
            codec="H.264",
            audio_codec="AAC-LC",
        )
        stats = ReceiverStats(
            start_time=now,
            end_time=end_time,
            duration=300,
            data_received=50000,
            average_bitrate=1333.3,
            peak_bitrate=2000.0,
            frames_decoded=9000,
            frames_dropped=5,
            errors=1,
            resolution=(1920, 1080),
            codec="H.264 Baseline",
        )
        return ServerSessionRecord(
            source_info=source,
            stats=stats,
            timestamp=now,
        )

    def test_serializes_all_source_info_fields(self):
        record = self._make_record()
        d = record.to_dict()
        si = d["source_info"]
        assert si["name"] == "Test Device"
        assert si["address"] == "AA:BB:CC:DD:EE:FF"
        assert si["model"] == "Test Model"
        assert si["resolution"] == [1920, 1080]
        assert si["codec"] == "H.264"
        assert si["audio_codec"] == "AAC-LC"

    def test_serializes_all_stats_fields(self):
        record = self._make_record()
        d = record.to_dict()
        stats = d["stats"]
        assert stats["start_time"] == "2024-06-15T10:30:00"
        assert stats["end_time"] is None
        assert stats["duration"] == 300
        assert stats["data_received"] == 50000
        assert stats["average_bitrate"] == 1333.3
        assert stats["peak_bitrate"] == 2000.0
        assert stats["frames_decoded"] == 9000
        assert stats["frames_dropped"] == 5
        assert stats["errors"] == 1
        assert stats["resolution"] == [1920, 1080]
        assert stats["codec"] == "H.264 Baseline"

    def test_serializes_timestamp_iso8601(self):
        record = self._make_record()
        d = record.to_dict()
        assert d["timestamp"] == "2024-06-15T10:30:00"

    def test_end_time_serialized_when_present(self):
        end = datetime(2024, 6, 15, 10, 35, 0)
        record = self._make_record(end_time=end)
        d = record.to_dict()
        assert d["stats"]["end_time"] == "2024-06-15T10:35:00"

    def test_end_time_null_when_none(self):
        record = self._make_record(end_time=None)
        d = record.to_dict()
        assert d["stats"]["end_time"] is None


class TestServerSessionRecordFromDict:
    """Test ServerSessionRecord.from_dict deserialization."""

    def _make_valid_dict(self):
        return {
            "source_info": {
                "name": "Test Device",
                "address": "AA:BB:CC:DD:EE:FF",
                "model": "Test Model",
                "resolution": [1920, 1080],
                "codec": "H.264",
                "audio_codec": "AAC-LC",
            },
            "stats": {
                "start_time": "2024-06-15T10:30:00",
                "end_time": None,
                "duration": 300,
                "data_received": 50000,
                "average_bitrate": 1333.3,
                "peak_bitrate": 2000.0,
                "frames_decoded": 9000,
                "frames_dropped": 5,
                "errors": 1,
                "resolution": [1920, 1080],
                "codec": "H.264 Baseline",
            },
            "timestamp": "2024-06-15T10:30:00",
        }

    def test_valid_roundtrip(self):
        now = datetime(2024, 6, 15, 10, 30, 0)
        source = SourceInfo(
            name="Test Device",
            address="AA:BB:CC:DD:EE:FF",
            model="Test Model",
            resolution=(1920, 1080),
            codec="H.264",
            audio_codec="AAC-LC",
        )
        stats = ReceiverStats(
            start_time=now,
            end_time=None,
            duration=300,
            data_received=50000,
            average_bitrate=1333.3,
            peak_bitrate=2000.0,
            frames_decoded=9000,
            frames_dropped=5,
            errors=1,
            resolution=(1920, 1080),
            codec="H.264 Baseline",
        )
        original = ServerSessionRecord(source_info=source, stats=stats, timestamp=now)
        serialized = original.to_dict()
        restored = ServerSessionRecord.from_dict(serialized)

        assert restored.source_info.name == original.source_info.name
        assert restored.source_info.address == original.source_info.address
        assert restored.source_info.model == original.source_info.model
        assert restored.source_info.resolution == original.source_info.resolution
        assert restored.source_info.codec == original.source_info.codec
        assert restored.source_info.audio_codec == original.source_info.audio_codec
        assert restored.stats.start_time == original.stats.start_time
        assert restored.stats.end_time == original.stats.end_time
        assert restored.stats.duration == original.stats.duration
        assert restored.stats.data_received == original.stats.data_received
        assert restored.stats.average_bitrate == original.stats.average_bitrate
        assert restored.stats.peak_bitrate == original.stats.peak_bitrate
        assert restored.stats.frames_decoded == original.stats.frames_decoded
        assert restored.stats.frames_dropped == original.stats.frames_dropped
        assert restored.stats.errors == original.stats.errors
        assert restored.stats.resolution == original.stats.resolution
        assert restored.stats.codec == original.stats.codec
        assert restored.timestamp == original.timestamp

    def test_roundtrip_with_end_time(self):
        now = datetime(2024, 6, 15, 10, 30, 0)
        end = datetime(2024, 6, 15, 10, 35, 0)
        source = SourceInfo(name="Device", address="11:22:33:44:55:66", model="Model")
        stats = ReceiverStats(start_time=now, end_time=end, duration=300, data_received=100)
        original = ServerSessionRecord(source_info=source, stats=stats, timestamp=now)
        serialized = original.to_dict()
        restored = ServerSessionRecord.from_dict(serialized)
        assert restored.stats.end_time == end

    def test_missing_source_info(self):
        data = self._make_valid_dict()
        del data["source_info"]
        with pytest.raises(ValueError, match="source_info"):
            ServerSessionRecord.from_dict(data)

    def test_missing_stats(self):
        data = self._make_valid_dict()
        del data["stats"]
        with pytest.raises(ValueError, match="stats"):
            ServerSessionRecord.from_dict(data)

    def test_missing_timestamp(self):
        data = self._make_valid_dict()
        del data["timestamp"]
        with pytest.raises(ValueError, match="timestamp"):
            ServerSessionRecord.from_dict(data)

    def test_missing_source_info_name(self):
        data = self._make_valid_dict()
        del data["source_info"]["name"]
        with pytest.raises(ValueError, match="name"):
            ServerSessionRecord.from_dict(data)

    def test_missing_stats_start_time(self):
        data = self._make_valid_dict()
        del data["stats"]["start_time"]
        with pytest.raises(ValueError, match="start_time"):
            ServerSessionRecord.from_dict(data)

    def test_invalid_timestamp_format(self):
        data = self._make_valid_dict()
        data["timestamp"] = "not-a-date"
        with pytest.raises(ValueError):
            ServerSessionRecord.from_dict(data)

    def test_invalid_stats_start_time_format(self):
        data = self._make_valid_dict()
        data["stats"]["start_time"] = "invalid"
        with pytest.raises(ValueError):
            ServerSessionRecord.from_dict(data)

    def test_non_dict_input(self):
        with pytest.raises(ValueError, match="must be a dictionary"):
            ServerSessionRecord.from_dict("not a dict")  # type: ignore

    def test_source_info_not_dict(self):
        data = self._make_valid_dict()
        data["source_info"] = "not a dict"
        with pytest.raises(ValueError, match="source_info must be a dictionary"):
            ServerSessionRecord.from_dict(data)

    def test_stats_not_dict(self):
        data = self._make_valid_dict()
        data["stats"] = "not a dict"
        with pytest.raises(ValueError, match="stats must be a dictionary"):
            ServerSessionRecord.from_dict(data)

    def test_no_partial_object_on_failure(self):
        """Ensure that from_dict does not create a partial object on failure."""
        data = self._make_valid_dict()
        # Make frames invalid (decoded < dropped) to trigger validation error
        data["stats"]["frames_decoded"] = 1
        data["stats"]["frames_dropped"] = 10
        with pytest.raises(ValueError):
            ServerSessionRecord.from_dict(data)
