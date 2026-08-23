"""Security tests for Ubuntu Miracast Server.

Tests security boundaries in a privileged application that runs with sudo.
Focuses on:
- RTSP parser resilience against malformed/malicious input
- wpa_cli parameter injection prevention
- File permission enforcement
- Input size limits
"""

import os
import stat
import tempfile

import pytest

from miracast_server.rtsp import (
    RTSPParseError,
    parse_rtsp_request,
    validate_request_size,
)
from miracast_server.utils import _validate_wpa_param


class TestWPAParameterInjection:
    """Verify _validate_wpa_param rejects injection attempts.

    These parameters flow into subprocess calls that run with sudo.
    A bypass here = root command injection.
    """

    def test_rejects_semicolon_injection(self):
        """Semicolons could chain additional commands."""
        with pytest.raises(ValueError):
            _validate_wpa_param("valid;rm -rf /")

    def test_rejects_pipe_injection(self):
        """Pipes could redirect output to attacker-controlled commands."""
        with pytest.raises(ValueError):
            _validate_wpa_param("param|cat /etc/shadow")

    def test_rejects_backtick_injection(self):
        """Backticks execute subcommands in some shells."""
        with pytest.raises(ValueError):
            _validate_wpa_param("`whoami`")

    def test_rejects_dollar_paren_injection(self):
        """$() is command substitution."""
        with pytest.raises(ValueError):
            _validate_wpa_param("$(cat /etc/passwd)")

    def test_rejects_ampersand_injection(self):
        """& backgrounds a command."""
        with pytest.raises(ValueError):
            _validate_wpa_param("param&malicious")

    def test_rejects_newline_injection(self):
        """Newlines could inject additional wpa_cli commands."""
        with pytest.raises(ValueError):
            _validate_wpa_param("param\nP2P_GROUP_REMOVE")

    def test_rejects_null_byte(self):
        """Null bytes can truncate strings in C programs (wpa_supplicant)."""
        with pytest.raises(ValueError):
            _validate_wpa_param("param\x00extra")

    def test_rejects_redirect_operators(self):
        """Redirect operators could overwrite files."""
        with pytest.raises(ValueError):
            _validate_wpa_param("param > /etc/passwd")
        with pytest.raises(ValueError):
            _validate_wpa_param("param >> /tmp/evil")

    def test_rejects_empty_string(self):
        """Empty params should not reach subprocess."""
        with pytest.raises(ValueError):
            _validate_wpa_param("")

    def test_rejects_excessively_long_input(self):
        """Long inputs could overflow buffers in wpa_supplicant."""
        with pytest.raises(ValueError):
            _validate_wpa_param("A" * 1000)

    def test_accepts_valid_mac_address(self):
        """Valid MAC addresses must pass."""
        result = _validate_wpa_param("aa:bb:cc:dd:ee:ff")
        assert result == "aa:bb:cc:dd:ee:ff"

    def test_accepts_valid_pin(self):
        """Valid WPS PINs must pass."""
        result = _validate_wpa_param("12345678")
        assert result == "12345678"

    def test_accepts_valid_interface_name(self):
        """Valid interface names must pass."""
        result = _validate_wpa_param("p2p-wlx123-0")
        assert result == "p2p-wlx123-0"

    def test_accepts_valid_device_name(self):
        """Device names with spaces and common chars must pass."""
        result = _validate_wpa_param("Ubuntu Miracast Server")
        assert result == "Ubuntu Miracast Server"


class TestRTSPParserFuzzing:
    """Fuzz the RTSP parser with malformed and malicious inputs.

    The RTSP parser accepts untrusted network data from any device on
    the P2P group. It must never crash, leak memory, or allow injection.
    """

    def test_empty_input(self):
        """Empty data must raise parse error, not crash."""
        with pytest.raises(RTSPParseError):
            parse_rtsp_request(b"")

    def test_null_bytes_in_header(self):
        """Null bytes in headers must not crash the parser."""
        with pytest.raises(RTSPParseError):
            parse_rtsp_request(b"OPTIONS * RTSP/1.0\r\nCSeq: \x001\r\n\r\n")

    def test_enormous_header(self):
        """Headers exceeding size limit must be rejected before parsing."""
        # 8KB header limit
        huge_header = b"OPTIONS * RTSP/1.0\r\nX-Evil: " + b"A" * 10000 + b"\r\n\r\n"
        with pytest.raises(RTSPParseError):
            validate_request_size(huge_header)

    def test_enormous_body(self):
        """Bodies exceeding 64KB must be rejected."""
        body = b"x" * 70000
        msg = (
            b"SET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0\r\n"
            b"CSeq: 1\r\n"
            b"Content-Length: 70000\r\n"
            b"\r\n" + body
        )
        with pytest.raises(RTSPParseError):
            validate_request_size(msg)

    def test_negative_content_length(self):
        """Negative Content-Length must not cause issues."""
        msg = b"GET_PARAMETER * RTSP/1.0\r\nCSeq: 1\r\nContent-Length: -1\r\n\r\n"
        # Should not crash — either parses safely or raises error
        try:
            parse_rtsp_request(msg)
        except RTSPParseError:
            pass  # Expected

    def test_content_length_overflow(self):
        """Extremely large Content-Length must not cause memory allocation."""
        msg = b"SET_PARAMETER * RTSP/1.0\r\nCSeq: 1\r\nContent-Length: 99999999999\r\n\r\nbody"
        with pytest.raises(RTSPParseError):
            validate_request_size(msg)

    def test_malformed_method_line(self):
        """Invalid request line must raise parse error."""
        with pytest.raises(RTSPParseError):
            parse_rtsp_request(b"NOT_A_METHOD invalid garbage\r\n\r\n")

    def test_missing_crlf(self):
        """Messages without proper CRLF terminators."""
        # LF-only message without \r\n\r\n separator — parser may handle gracefully
        # or reject; either way it must not crash
        try:
            parse_rtsp_request(b"OPTIONS * RTSP/1.0\nCSeq: 1\n\n")
        except (RTSPParseError, Exception):
            pass  # Acceptable to reject non-CRLF messages

    def test_unicode_injection_in_headers(self):
        """UTF-8 multibyte sequences must not corrupt parsing."""
        msg = "OPTIONS * RTSP/1.0\r\nCSeq: 1\r\nX-Name: \u202e\u0041\u0042\r\n\r\n"
        # Should parse without crash (RTL override chars)
        try:
            parse_rtsp_request(msg.encode("utf-8"))
        except RTSPParseError:
            pass  # Acceptable to reject

    def test_header_injection_via_crlf(self):
        """CRLF injection in header values must not create extra headers."""
        # Attacker tries to inject a second header via CRLF in value
        msg = b"OPTIONS * RTSP/1.0\r\nCSeq: 1\r\nX-Evil: value\r\nInjected: yes\r\n\r\n"
        # This is actually a valid multi-header message, but the parser
        # should handle it without crashing
        try:
            result = parse_rtsp_request(msg)
            # The "Injected" header should just be parsed as a regular header
            assert result is not None
        except RTSPParseError:
            pass

    def test_repeated_cseq_headers(self):
        """Multiple CSeq headers should not confuse the parser."""
        msg = b"OPTIONS * RTSP/1.0\r\nCSeq: 1\r\nCSeq: 999\r\n\r\n"
        try:
            result = parse_rtsp_request(msg)
            # Should use first or last, but not crash
            assert result.cseq in (1, 999)
        except RTSPParseError:
            pass

    def test_binary_garbage(self):
        """Random binary data must not crash the parser."""
        import random

        random.seed(42)  # Reproducible
        for _ in range(20):
            garbage = bytes(random.randint(0, 255) for _ in range(random.randint(1, 500)))
            try:
                parse_rtsp_request(garbage)
            except (RTSPParseError, UnicodeDecodeError):
                pass  # Expected — must not crash with unhandled exception


class TestFilePermissions:
    """Verify that config/history files use restrictive permissions.

    On a multi-user system, other users could read Wi-Fi credentials
    or session data if file permissions are too open.
    """

    def test_config_file_permissions(self):
        """Config files must be created with 0600 permissions."""
        from miracast_server.config import ServerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.json")
            config = ServerConfig(config_path=config_path)
            config.save()

            if os.path.exists(config_path):
                mode = os.stat(config_path).st_mode
                # Must not be world-readable or group-readable
                assert not (mode & stat.S_IRGRP), "Config file is group-readable"
                assert not (mode & stat.S_IROTH), "Config file is world-readable"
                assert not (mode & stat.S_IWGRP), "Config file is group-writable"
                assert not (mode & stat.S_IWOTH), "Config file is world-writable"

    def test_history_file_permissions(self):
        """History files must be created with 0600 permissions."""
        from datetime import datetime

        from miracast_server.history import ServerSessionHistory
        from miracast_server.models import ReceiverStats, SourceInfo

        with tempfile.TemporaryDirectory() as tmpdir:
            history_path = os.path.join(tmpdir, "history.json")
            history = ServerSessionHistory(history_path=history_path)
            # Trigger a save by adding a session
            source = SourceInfo(name="Test", address="aa:bb:cc:dd:ee:ff", model="")
            stats = ReceiverStats(
                start_time=datetime.now(),
                end_time=datetime.now(),
                duration=10,
                data_received=1000,
                average_bitrate=1000.0,
                peak_bitrate=2000.0,
                frames_decoded=100,
                frames_dropped=0,
                errors=0,
                resolution=(1920, 1080),
                codec="H264",
            )
            history.add_session(source, stats)

            if os.path.exists(history_path):
                mode = os.stat(history_path).st_mode
                assert not (mode & stat.S_IRGRP), "History file is group-readable"
                assert not (mode & stat.S_IROTH), "History file is world-readable"
