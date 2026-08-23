"""RTSP message parsing and generation for Miracast WFD sessions.

Implements RTSP request parsing, response building, and WFD parameter
handling for the Miracast sink RTSP protocol flow.
"""

import logging
import re
from dataclasses import dataclass, field
from enum import IntEnum

logger = logging.getLogger(__name__)

# RTSP size limits (security constraints)
_MAX_HEADER_SIZE = 8192  # 8 KB max header block
_MAX_BODY_SIZE = 65536  # 64 KB max body


class RTSPMethod(IntEnum):
    """Known RTSP methods used in WFD sessions."""

    OPTIONS = 1
    GET_PARAMETER = 2
    SET_PARAMETER = 3
    SETUP = 4
    PLAY = 5
    TEARDOWN = 6
    PAUSE = 7


# String to enum mapping
_METHOD_MAP = {
    "OPTIONS": RTSPMethod.OPTIONS,
    "GET_PARAMETER": RTSPMethod.GET_PARAMETER,
    "SET_PARAMETER": RTSPMethod.SET_PARAMETER,
    "SETUP": RTSPMethod.SETUP,
    "PLAY": RTSPMethod.PLAY,
    "TEARDOWN": RTSPMethod.TEARDOWN,
    "PAUSE": RTSPMethod.PAUSE,
}

# RTSP status codes
RTSP_OK = 200
RTSP_BAD_REQUEST = 400
RTSP_NOT_FOUND = 404
RTSP_METHOD_NOT_ALLOWED = 405
RTSP_REQUEST_ENTITY_TOO_LARGE = 413
RTSP_INTERNAL_SERVER_ERROR = 500
RTSP_NOT_IMPLEMENTED = 501

_STATUS_PHRASES = {
    200: "OK",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    413: "Request Entity Too Large",
    451: "Parameter Not Understood",
    500: "Internal Server Error",
    501: "Not Implemented",
}


class RTSPParseError(Exception):
    """Raised when an RTSP message cannot be parsed."""

    def __init__(self, message: str, status_code: int = RTSP_BAD_REQUEST):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class RTSPRequest:
    """Parsed RTSP request."""

    method: RTSPMethod
    uri: str
    version: str
    cseq: int
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""
    content_length: int = 0


@dataclass
class RTSPResponse:
    """RTSP response to be sent."""

    status_code: int
    cseq: int
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""

    @property
    def status_phrase(self) -> str:
        return _STATUS_PHRASES.get(self.status_code, "Unknown")

    def serialize(self) -> bytes:
        """Serialize the response to bytes for sending over the wire."""
        lines = [f"RTSP/1.0 {self.status_code} {self.status_phrase}"]
        lines.append(f"CSeq: {self.cseq}")

        for key, value in self.headers.items():
            lines.append(f"{key}: {value}")

        if self.body:
            lines.append(f"Content-Length: {len(self.body)}")
            lines.append("")
            lines.append(self.body)
        else:
            lines.append("Content-Length: 0")
            lines.append("")
            lines.append("")

        return "\r\n".join(lines).encode("utf-8")


def parse_rtsp_request(data: bytes) -> RTSPRequest:
    """Parse an RTSP request from raw bytes.

    Validates size limits, required headers, and message structure.

    Args:
        data: Raw bytes received from the RTSP source.

    Returns:
        Parsed RTSPRequest object.

    Raises:
        RTSPParseError: If the request is malformed, too large, or missing
                        required headers.
    """
    if not data:
        raise RTSPParseError("Empty request")

    # Split header and body
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception as e:
        raise RTSPParseError("Invalid encoding") from e

    # Find header/body separator
    separator_idx = text.find("\r\n\r\n")
    if separator_idx == -1:
        separator_idx = text.find("\n\n")
        if separator_idx == -1:
            # No body separator — treat entire thing as headers
            header_text = text
            body_text = ""
        else:
            header_text = text[:separator_idx]
            body_text = text[separator_idx + 2 :]
    else:
        header_text = text[:separator_idx]
        body_text = text[separator_idx + 4 :]

    # Validate header size
    if len(header_text.encode("utf-8")) > _MAX_HEADER_SIZE:
        raise RTSPParseError(
            "Request header exceeds maximum size",
            status_code=RTSP_REQUEST_ENTITY_TOO_LARGE,
        )

    # Validate body size
    if len(body_text.encode("utf-8")) > _MAX_BODY_SIZE:
        raise RTSPParseError(
            "Request body exceeds maximum size",
            status_code=RTSP_REQUEST_ENTITY_TOO_LARGE,
        )

    # Parse request line
    lines = header_text.split("\r\n") if "\r\n" in header_text else header_text.split("\n")
    if not lines:
        raise RTSPParseError("No request line")

    request_line = lines[0].strip()
    parts = request_line.split()
    if len(parts) < 3:
        raise RTSPParseError(f"Malformed request line: {request_line!r}")

    method_str = parts[0]
    uri = parts[1]
    version = parts[2]

    # Validate method
    method = _METHOD_MAP.get(method_str.upper())
    if method is None:
        raise RTSPParseError(
            f"Unknown method: {method_str}",
            status_code=RTSP_NOT_IMPLEMENTED,
        )

    # Validate version
    if not version.startswith("RTSP/"):
        raise RTSPParseError(f"Invalid protocol version: {version}")

    # Parse headers
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        headers[key.strip()] = value.strip()

    # Extract CSeq (required)
    cseq_str = headers.get("CSeq") or headers.get("cseq") or headers.get("CSEQ")
    if cseq_str is None:
        raise RTSPParseError("Missing required CSeq header")

    try:
        cseq = int(cseq_str)
    except ValueError as e:
        raise RTSPParseError(f"Invalid CSeq value: {cseq_str!r}") from e

    if cseq < 0:
        raise RTSPParseError(f"Invalid CSeq value: {cseq}")

    # Extract Content-Length
    content_length_str = (
        headers.get("Content-Length")
        or headers.get("content-length")
        or headers.get("Content-length")
        or "0"
    )
    try:
        content_length = int(content_length_str)
    except ValueError:
        content_length = 0

    # Trim body to content-length
    if content_length > 0 and body_text:
        body_text = body_text[:content_length]

    return RTSPRequest(
        method=method,
        uri=uri,
        version=version,
        cseq=cseq,
        headers=headers,
        body=body_text,
        content_length=content_length,
    )


def build_response(
    status_code: int,
    cseq: int,
    headers: dict[str, str] | None = None,
    body: str = "",
) -> RTSPResponse:
    """Build an RTSP response.

    Args:
        status_code: HTTP/RTSP status code.
        cseq: CSeq value to echo from the request.
        headers: Additional response headers.
        body: Response body text.

    Returns:
        RTSPResponse object ready to serialize.
    """
    return RTSPResponse(
        status_code=status_code,
        cseq=cseq,
        headers=headers or {},
        body=body,
    )


def build_options_response(cseq: int) -> RTSPResponse:
    """Build response to OPTIONS request.

    Advertises supported methods for the WFD sink per FR-RN02.
    """
    return build_response(
        status_code=RTSP_OK,
        cseq=cseq,
        headers={
            "Public": "org.wfa.wfd1.0, GET_PARAMETER, SET_PARAMETER, SETUP, PLAY, TEARDOWN",
        },
    )


def build_options_request(cseq: int) -> bytes:
    """Build an OPTIONS request from the sink to the source (M2).

    The sink queries the source's supported methods.
    """
    lines = [
        "OPTIONS * RTSP/1.0",
        f"CSeq: {cseq}",
        "Require: org.wfa.wfd1.0",
        "",
        "",
    ]
    return "\r\n".join(lines).encode("utf-8")


# ─── WFD Parameter Handling ───────────────────────────────────────────────────


@dataclass
class WFDVideoFormat:
    """Parsed WFD video format parameters."""

    native_index: int = 0
    preferred_display_mode: int = 0
    profile: int = 0x02  # CHP
    level: int = 0x10  # Level 4.2
    cea_bitmap: int = 0x0001DEFF  # Standard supported resolutions
    vesa_bitmap: int = 0x00000000
    hh_bitmap: int = 0x00000000
    latency: int = 0
    min_slice_size: int = 0
    slice_enc_params: int = 0
    frame_rate_control: int = 0
    max_hres: str = "none"
    max_vres: str = "none"

    def to_wfd_string(self) -> str:
        """Serialize to WFD response format."""
        return (
            f"{self.native_index:02X} {self.preferred_display_mode:02X} "
            f"{self.profile:02X} {self.level:02X} "
            f"{self.cea_bitmap:08X} {self.vesa_bitmap:08X} {self.hh_bitmap:08X} "
            f"{self.latency:02X} {self.min_slice_size:04X} {self.slice_enc_params:04X} "
            f"{self.frame_rate_control:02X} {self.max_hres} {self.max_vres}"
        )


@dataclass
class WFDAudioCodec:
    """Parsed WFD audio codec parameters."""

    codec: str = "AAC"
    modes_bitmap: int = 0x00000007  # 48kHz/16bit/2ch, 44.1kHz/16bit/2ch, 48kHz/16bit/4ch
    latency: int = 0

    def to_wfd_string(self) -> str:
        """Serialize to WFD response format."""
        return f"{self.codec} {self.modes_bitmap:08X} {self.latency:02X}"


@dataclass
class WFDParameters:
    """Parsed WFD parameters from SET_PARAMETER request body."""

    video_formats: WFDVideoFormat | None = None
    audio_codecs: WFDAudioCodec | None = None
    presentation_url: str = ""
    client_rtp_ports: str = ""
    content_protection: str = "none"
    rtp_port: int = 0
    video_codec: str = ""
    audio_codec: str = ""
    resolution: tuple[int, int] = (0, 0)


def parse_wfd_parameters(body: str) -> WFDParameters:
    """Parse WFD parameters from an RTSP SET_PARAMETER body.

    Args:
        body: The request body containing WFD parameter lines.

    Returns:
        WFDParameters with parsed values.
    """
    params = WFDParameters()

    for line in body.strip().split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue

        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()

        if key == "wfd_video_formats":
            params.video_formats = _parse_video_formats(value)
            params.video_codec = "H264"
            # Try to determine resolution from CEA bitmap
            if params.video_formats:
                params.resolution = _resolution_from_cea_bitmap(params.video_formats.cea_bitmap)

        elif key == "wfd_audio_codecs":
            params.audio_codecs = _parse_audio_codecs(value)
            if params.audio_codecs:
                params.audio_codec = params.audio_codecs.codec

        elif key == "wfd_presentation_url":
            params.presentation_url = value

        elif key == "wfd_client_rtp_ports":
            params.client_rtp_ports = value
            # Extract RTP port from "RTP/AVP/UDP;unicast <port> 0 mode=play"
            re.search(r"(\d+)", value.split(";")[-1] if ";" in value else value)
            parts = value.split()
            if len(parts) >= 2:
                try:
                    params.rtp_port = int(parts[1])
                except ValueError:
                    pass

        elif key == "wfd_content_protection":
            params.content_protection = value

    return params


def _parse_video_formats(value: str) -> WFDVideoFormat:
    """Parse wfd_video_formats value string."""
    parts = value.strip().split()
    fmt = WFDVideoFormat()

    try:
        if len(parts) >= 1:
            fmt.native_index = int(parts[0], 16)
        if len(parts) >= 2:
            fmt.preferred_display_mode = int(parts[1], 16)
        if len(parts) >= 3:
            fmt.profile = int(parts[2], 16)
        if len(parts) >= 4:
            fmt.level = int(parts[3], 16)
        if len(parts) >= 5:
            fmt.cea_bitmap = int(parts[4], 16)
        if len(parts) >= 6:
            fmt.vesa_bitmap = int(parts[5], 16)
        if len(parts) >= 7:
            fmt.hh_bitmap = int(parts[6], 16)
        if len(parts) >= 8:
            fmt.latency = int(parts[7], 16)
        if len(parts) >= 9:
            fmt.min_slice_size = int(parts[8], 16)
        if len(parts) >= 10:
            fmt.slice_enc_params = int(parts[9], 16)
        if len(parts) >= 11:
            fmt.frame_rate_control = int(parts[10], 16)
        if len(parts) >= 12:
            fmt.max_hres = parts[11]
        if len(parts) >= 13:
            fmt.max_vres = parts[12]
    except (ValueError, IndexError) as e:
        logger.warning("Failed to parse video formats '%s': %s", value, e)

    return fmt


def _parse_audio_codecs(value: str) -> WFDAudioCodec:
    """Parse wfd_audio_codecs value string."""
    parts = value.strip().split()
    codec = WFDAudioCodec()

    try:
        if len(parts) >= 1:
            codec.codec = parts[0]
        if len(parts) >= 2:
            codec.modes_bitmap = int(parts[1], 16)
        if len(parts) >= 3:
            codec.latency = int(parts[2], 16)
    except (ValueError, IndexError) as e:
        logger.warning("Failed to parse audio codecs '%s': %s", value, e)

    return codec


def _resolution_from_cea_bitmap(bitmap: int) -> tuple[int, int]:
    """Determine the highest resolution from a CEA bitmap.

    Common CEA resolutions by bit position:
      Bit 0: 640x480p60
      Bit 5: 1280x720p30
      Bit 6: 1280x720p60
      Bit 7: 1920x1080p30
      Bit 8: 1920x1080p60
    """
    _CEA_RESOLUTIONS = {
        8: (1920, 1080),
        7: (1920, 1080),
        6: (1280, 720),
        5: (1280, 720),
        4: (720, 576),
        3: (720, 576),
        2: (720, 480),
        1: (720, 480),
        0: (640, 480),
    }

    # Return the highest resolution supported
    for bit in sorted(_CEA_RESOLUTIONS.keys(), reverse=True):
        if bitmap & (1 << bit):
            return _CEA_RESOLUTIONS[bit]

    return (1920, 1080)  # Default


def build_capability_response_body(
    rtsp_port: int = 7236,
    rtp_port: int = 1028,
    video_formats: WFDVideoFormat | None = None,
    audio_codecs: WFDAudioCodec | None = None,
) -> str:
    """Build the WFD capability response body for GET_PARAMETER.

    This is the sink's response to M3 (source queries capabilities).

    Args:
        rtsp_port: RTSP control port.
        rtp_port: RTP receive port.
        video_formats: Video format capabilities (defaults if None).
        audio_codecs: Audio codec capabilities (defaults if None).

    Returns:
        Response body string with WFD parameters.
    """
    if video_formats is None:
        video_formats = WFDVideoFormat()
    if audio_codecs is None:
        audio_codecs = WFDAudioCodec()

    lines = [
        f"wfd_video_formats: {video_formats.to_wfd_string()}",
        f"wfd_audio_codecs: {audio_codecs.to_wfd_string()}",
        f"wfd_client_rtp_ports: RTP/AVP/UDP;unicast {rtp_port} 0 mode=play",
        "wfd_content_protection: none",
        "wfd_coupled_sink: none",
    ]

    return "\r\n".join(lines)


def validate_request_size(data: bytes) -> None:
    """Validate that raw request data does not exceed size limits.

    Args:
        data: Raw bytes of the incoming request.

    Raises:
        RTSPParseError: If the request exceeds size limits.
    """
    if len(data) > _MAX_HEADER_SIZE + _MAX_BODY_SIZE:
        raise RTSPParseError(
            "Request exceeds maximum allowed size",
            status_code=RTSP_REQUEST_ENTITY_TOO_LARGE,
        )
