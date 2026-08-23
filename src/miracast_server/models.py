"""Data models for the Ubuntu Miracast Server."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# MAC address pattern: XX:XX:XX:XX:XX:XX where X is hex (0-9, A-F, a-f)
_MAC_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def _validate_mac_address(value: str, field_name: str) -> None:
    """Validate that value is a valid MAC address in XX:XX:XX:XX:XX:XX format."""
    if not _MAC_PATTERN.match(value):
        raise ValueError(f"{field_name}: must be a valid MAC address in XX:XX:XX:XX:XX:XX format")


def _validate_ipv4_address(value: str, field_name: str) -> None:
    """Validate that value is a valid IPv4 address in dotted-decimal notation."""
    parts = value.split(".")
    if len(parts) != 4:
        raise ValueError(f"{field_name}: must be a valid IPv4 address in dotted-decimal notation")
    for part in parts:
        # No leading zeros allowed (except "0" itself)
        if len(part) > 1 and part.startswith("0"):
            raise ValueError(
                f"{field_name}: must be a valid IPv4 address (no leading zeros in octets)"
            )
        try:
            octet = int(part)
        except ValueError as e:
            raise ValueError(
                f"{field_name}: must be a valid IPv4 address in dotted-decimal notation"
            ) from e
        if octet < 0 or octet > 255:
            raise ValueError(f"{field_name}: must be a valid IPv4 address (octets must be 0-255)")


def _validate_group_interface(value: str, field_name: str) -> None:
    """Validate that group_interface is between 2 and 16 characters."""
    if len(value) < 2 or len(value) > 16:
        raise ValueError(f"{field_name}: must be between 2 and 16 characters")


def _validate_connected_at(value: datetime, field_name: str) -> None:
    """Validate that connected_at is not in the future (with 1 second tolerance)."""
    now = datetime.now()
    tolerance = timedelta(seconds=1)
    if value > now + tolerance:
        raise ValueError(f"{field_name}: must not be in the future")


@dataclass
class IncomingConnection:
    """Represents a connected Miracast source.

    Validates all fields on construction via __post_init__.
    Raises ValueError with field name and reason on validation failure.
    """

    peer_address: str
    peer_ip: str
    peer_name: str
    group_interface: str
    our_ip: str
    connected_at: datetime
    go_role: bool = True

    def __post_init__(self) -> None:
        """Validate all fields after dataclass initialization."""
        _validate_mac_address(self.peer_address, "peer_address")
        _validate_ipv4_address(self.peer_ip, "peer_ip")
        _validate_group_interface(self.group_interface, "group_interface")
        _validate_ipv4_address(self.our_ip, "our_ip")
        _validate_connected_at(self.connected_at, "connected_at")


def _validate_non_negative_int(value: int, field_name: str) -> None:
    """Validate that value is a non-negative integer."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name}: must be a non-negative integer")
    if value < 0:
        raise ValueError(f"{field_name}: must be a non-negative integer")


def _validate_frames(frames_decoded: int, frames_dropped: int) -> None:
    """Validate that frames_decoded >= frames_dropped >= 0."""
    if not isinstance(frames_decoded, int) or isinstance(frames_decoded, bool):
        raise ValueError("frames_decoded: must be a non-negative integer")
    if not isinstance(frames_dropped, int) or isinstance(frames_dropped, bool):
        raise ValueError("frames_dropped: must be a non-negative integer")
    if frames_decoded < 0:
        raise ValueError("frames_decoded: must be a non-negative integer")
    if frames_dropped < 0:
        raise ValueError("frames_dropped: must be a non-negative integer")
    if frames_decoded < frames_dropped:
        raise ValueError("frames_decoded: must be greater than or equal to frames_dropped")


@dataclass
class ReceiverStats:
    """Statistics for a receiving session.

    Validates fields on construction via __post_init__.
    Raises ValueError with field name and reason on validation failure.
    """

    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None
    duration: int = 0
    data_received: int = 0
    average_bitrate: float = 0.0
    peak_bitrate: float = 0.0
    frames_decoded: int = 0
    frames_dropped: int = 0
    errors: int = 0
    resolution: tuple[int, int] = (0, 0)
    codec: str = ""

    def __post_init__(self) -> None:
        """Validate all fields after dataclass initialization."""
        _validate_non_negative_int(self.duration, "duration")
        _validate_non_negative_int(self.data_received, "data_received")
        _validate_frames(self.frames_decoded, self.frames_dropped)


@dataclass
class SourceInfo:
    """Information about a Miracast source device."""

    name: str
    address: str
    model: str
    resolution: tuple[int, int] = (0, 0)
    codec: str = ""
    audio_codec: str = ""


@dataclass
class ServerSessionRecord:
    """Complete record of a receiving session.

    Provides to_dict/from_dict for JSON serialization with ISO 8601 datetimes.
    Raises ValueError on deserialization if required fields are missing or unparseable.
    """

    source_info: SourceInfo
    stats: ReceiverStats
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dictionary.

        Datetimes are formatted as ISO 8601 strings.
        None values are represented as JSON null (Python None).
        Resolution tuples are stored as lists.
        """
        return {
            "source_info": {
                "name": self.source_info.name,
                "address": self.source_info.address,
                "model": self.source_info.model,
                "resolution": list(self.source_info.resolution),
                "codec": self.source_info.codec,
                "audio_codec": self.source_info.audio_codec,
            },
            "stats": {
                "start_time": self.stats.start_time.isoformat(),
                "end_time": self.stats.end_time.isoformat() if self.stats.end_time else None,
                "duration": self.stats.duration,
                "data_received": self.stats.data_received,
                "average_bitrate": self.stats.average_bitrate,
                "peak_bitrate": self.stats.peak_bitrate,
                "frames_decoded": self.stats.frames_decoded,
                "frames_dropped": self.stats.frames_dropped,
                "errors": self.stats.errors,
                "resolution": list(self.stats.resolution),
                "codec": self.stats.codec,
            },
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ServerSessionRecord":
        """Deserialize from a dictionary.

        Parses ISO 8601 datetime strings back to datetime objects.
        Raises ValueError if required fields are missing or values are unparseable.
        Does not create partial objects on failure.
        """
        try:
            # Validate top-level structure
            if not isinstance(data, dict):
                raise ValueError("data must be a dictionary")

            for key in ("source_info", "stats", "timestamp"):
                if key not in data:
                    raise ValueError(f"missing required field: {key}")

            # Parse source_info
            si_data = data["source_info"]
            if not isinstance(si_data, dict):
                raise ValueError("source_info must be a dictionary")
            for key in ("name", "address", "model"):
                if key not in si_data:
                    raise ValueError(f"source_info missing required field: {key}")

            source_info = SourceInfo(
                name=si_data["name"],
                address=si_data["address"],
                model=si_data["model"],
                resolution=tuple(si_data.get("resolution", [0, 0])),
                codec=si_data.get("codec", ""),
                audio_codec=si_data.get("audio_codec", ""),
            )

            # Parse stats
            stats_data = data["stats"]
            if not isinstance(stats_data, dict):
                raise ValueError("stats must be a dictionary")
            for key in (
                "start_time",
                "duration",
                "data_received",
                "frames_decoded",
                "frames_dropped",
            ):
                if key not in stats_data:
                    raise ValueError(f"stats missing required field: {key}")

            start_time = datetime.fromisoformat(stats_data["start_time"])
            end_time_raw = stats_data.get("end_time")
            end_time = datetime.fromisoformat(end_time_raw) if end_time_raw is not None else None

            stats = ReceiverStats(
                start_time=start_time,
                end_time=end_time,
                duration=stats_data["duration"],
                data_received=stats_data["data_received"],
                average_bitrate=float(stats_data.get("average_bitrate", 0.0)),
                peak_bitrate=float(stats_data.get("peak_bitrate", 0.0)),
                frames_decoded=stats_data["frames_decoded"],
                frames_dropped=stats_data["frames_dropped"],
                errors=int(stats_data.get("errors", 0)),
                resolution=tuple(stats_data.get("resolution", [0, 0])),
                codec=stats_data.get("codec", ""),
            )

            # Parse timestamp
            timestamp = datetime.fromisoformat(data["timestamp"])

            return cls(
                source_info=source_info,
                stats=stats,
                timestamp=timestamp,
            )

        except (KeyError, TypeError, IndexError) as e:
            raise ValueError(f"failed to deserialize ServerSessionRecord: {e}") from e
