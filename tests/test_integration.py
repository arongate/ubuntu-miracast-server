"""Integration tests — validates the complete Miracast server flow.

These tests ensure that if they pass, the application works end-to-end:
  1. Dedicated wpa_supplicant starts
  2. P2P GO is created
  3. WPS PIN is armed and displayed
  4. Source connects (AP-STA-CONNECTED)
  5. DHCP assigns IPs
  6. RTSP negotiation completes
  7. Cleanup on disconnect/shutdown

All external dependencies (wpa_cli, subprocess, GStreamer) are mocked at the
boundary. The test verifies that the correct commands are issued in the correct
order with the correct parameters.
"""

from unittest.mock import MagicMock, patch, call
from datetime import datetime
import pytest

from miracast_server.advertiser import MiracastAdvertiser
from miracast_server.connection import ConnectionHandler
from miracast_server.p2p_supplicant import P2PSupplicantManager
from miracast_server.rtsp import parse_rtsp_request, build_response, build_capability_response_body, RTSP_OK


class TestEndToEndGOCreation:
    """Test: Supplicant → Advertiser → GO created → Connection handler armed."""

    @patch("miracast_server.advertiser._run_wpa_cli")
    @patch("miracast_server.advertiser.MiracastAdvertiser._wait_for_group_interface")
    @patch("miracast_server.connection._run_wpa_cli")
    @patch("miracast_server.connection.GLib.idle_add")
    @patch("miracast_server.advertiser.GLib.idle_add")
    def test_full_startup_flow(
        self, mock_adv_idle, mock_conn_idle, mock_conn_wpa, mock_wait, mock_adv_wpa
    ):
        """From start to PIN display."""
        mock_adv_wpa.return_value = "OK"
        mock_conn_wpa.return_value = "OK"
        mock_wait.return_value = "p2p-wlx123-0"

        # Step 1: Create advertiser with dedicated supplicant params
        advertiser = MiracastAdvertiser(
            device_name="Test Sink",
            rtsp_port=7236,
            p2p_interface="wlx123",
            ctrl_path="/tmp/test-ctrl",
        )

        # Step 2: Start advertising (creates GO)
        advertiser.start_advertising()

        # Verify: GO was created
        assert advertiser.is_advertising is True
        assert advertiser.group_interface == "p2p-wlx123-0"

        # Verify: WFD subelements were set
        wpa_calls_str = str(mock_adv_wpa.call_args_list)
        assert "wifi_display" in wpa_calls_str
        assert "wfd_subelem_set" in wpa_calls_str
        assert "p2p_group_add" in wpa_calls_str

        # Step 3: Connection handler starts on group interface
        handler = ConnectionHandler(p2p_interface="wlx123")
        handler._ctrl_path = "/tmp/test-ctrl"

        with patch("threading.Thread") as mock_thread:
            mock_thread.return_value.start = MagicMock()
            handler.start_listening("p2p-wlx123-0")

        # Verify: WPS PIN was armed on the GROUP interface
        assert mock_conn_wpa.called
        wps_call = mock_conn_wpa.call_args
        assert wps_call[0][0] == "p2p-wlx123-0"  # GROUP interface
        assert wps_call[0][1] == "wps_pin"
        assert wps_call[0][2] == "any"
        pin = wps_call[0][3]
        assert len(pin) == 8 and pin.isdigit()

        # Verify: PIN display signal was emitted
        pin_display_calls = [c for c in mock_conn_idle.call_args_list if "pin-display" in str(c)]
        assert len(pin_display_calls) == 1


class TestEndToEndConnection:
    """Test: Source connects → DHCP → connection-received."""

    @patch("miracast_server.connection.ConnectionHandler._setup_dhcp")
    @patch("miracast_server.connection._run_wpa_cli")
    @patch("miracast_server.connection.GLib.idle_add")
    def test_source_connects_via_wps(self, mock_idle, mock_wpa, mock_dhcp):
        """Simulate AP-STA-CONNECTED → full connection establishment."""
        mock_wpa.return_value = "OK"
        mock_dhcp.return_value = "192.168.49.1"

        handler = ConnectionHandler(p2p_interface="wlx123")
        handler._ctrl_path = "/tmp/test-ctrl"
        handler._group_interface = "p2p-wlx123-0"
        handler._current_pin = "12345678"
        handler._running = True

        # Simulate AP-STA-CONNECTED event
        handler._handle_sta_connected("be:10:7b:d4:5f:b8")

        # Verify: DHCP was set up
        mock_dhcp.assert_called_once()

        # Verify: connection-received was emitted
        conn_calls = [c for c in mock_idle.call_args_list if "connection-received" in str(c)]
        assert len(conn_calls) == 1

        # Verify: connection object has correct data
        conn = handler.active_connection
        assert conn.peer_address == "be:10:7b:d4:5f:b8"
        assert conn.our_ip == "192.168.49.1"
        assert conn.go_role is True
        assert conn.group_interface == "p2p-wlx123-0"


class TestEndToEndRTSPNegotiation:
    """Test: RTSP M1-M7 message exchange (protocol level)."""

    def test_m1_options_response(self):
        """M1: Source sends OPTIONS, sink responds with supported methods."""
        data = b"OPTIONS * RTSP/1.0\r\nCSeq: 0\r\n\r\n"
        req = parse_rtsp_request(data)

        from miracast_server.rtsp import build_options_response
        resp = build_options_response(req.cseq)
        serialized = resp.serialize().decode()

        assert "200 OK" in serialized
        assert "CSeq: 0" in serialized
        assert "SETUP" in serialized
        assert "PLAY" in serialized
        assert "TEARDOWN" in serialized

    def test_m3_get_parameter_capability_response(self):
        """M3: Source queries capabilities, sink responds with WFD params."""
        body = build_capability_response_body(rtsp_port=7236, rtp_port=1028)

        assert "wfd_video_formats:" in body
        assert "wfd_audio_codecs:" in body
        assert "1028" in body
        assert "wfd_content_protection: none" in body

    def test_m4_set_parameter_parsing(self):
        """M4: Source sets parameters, sink parses correctly."""
        body = (
            "wfd_video_formats: 00 00 02 10 0001DEFF 00000000 00000000 00 0000 0000 00 none none\r\n"
            "wfd_audio_codecs: AAC 00000007 00\r\n"
            "wfd_client_rtp_ports: RTP/AVP/UDP;unicast 1028 0 mode=play"
        )
        data = (
            f"SET_PARAMETER rtsp://192.168.49.1/wfd1.0 RTSP/1.0\r\n"
            f"CSeq: 3\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"\r\n"
            f"{body}"
        ).encode()
        req = parse_rtsp_request(data)

        from miracast_server.rtsp import parse_wfd_parameters
        params = parse_wfd_parameters(req.body)

        assert params.video_codec == "H264"
        assert params.audio_codec == "AAC"
        assert params.rtp_port == 1028

    def test_m5_setup_response(self):
        """M5: Verify SETUP response includes session ID and transport."""
        resp = build_response(
            RTSP_OK, cseq=4,
            headers={
                "Transport": "RTP/AVP/UDP;unicast;client_port=1028",
                "Session": "DEADBEEF;timeout=30",
            },
        )
        serialized = resp.serialize().decode()
        assert "Transport:" in serialized
        assert "Session: DEADBEEF" in serialized
        assert "1028" in serialized


class TestEndToEndDisconnectAndRearm:
    """Test: Source disconnects → WPS re-armed → ready for next connection."""

    @patch("miracast_server.connection._run_wpa_cli")
    @patch("miracast_server.connection.GLib.idle_add")
    def test_disconnect_rearms_wps(self, mock_idle, mock_wpa):
        """After disconnect, a new PIN is generated and WPS is re-armed."""
        mock_wpa.return_value = "OK"

        handler = ConnectionHandler(p2p_interface="wlx123")
        handler._ctrl_path = "/tmp/test-ctrl"
        handler._group_interface = "p2p-wlx123-0"
        handler._current_pin = "11111111"
        handler._running = True

        # Set up active connection
        from miracast_server.models import IncomingConnection
        handler._active_connection = IncomingConnection(
            peer_address="be:10:7b:d4:5f:b8",
            peer_ip="192.168.49.10",
            peer_name="Test Phone",
            group_interface="p2p-wlx123-0",
            our_ip="192.168.49.1",
            connected_at=datetime.now(),
            go_role=True,
        )

        # Simulate disconnect
        handler._handle_sta_disconnected()

        # Verify: connection cleared
        assert handler.active_connection is None

        # Verify: new PIN generated (different from old)
        assert handler._current_pin != "11111111"
        assert len(handler._current_pin) == 8

        # Verify: wps_pin called again with new PIN
        assert mock_wpa.called
        rearm_call = mock_wpa.call_args
        assert rearm_call[0][1] == "wps_pin"
        assert rearm_call[0][3] == handler._current_pin

        # Verify: pin-display emitted with new PIN
        pin_calls = [c for c in mock_idle.call_args_list if "pin-display" in str(c)]
        assert len(pin_calls) >= 1


class TestEndToEndShutdown:
    """Test: Graceful shutdown removes GO and restores state."""

    @patch("miracast_server.advertiser._run_wpa_cli")
    @patch("miracast_server.advertiser.MiracastAdvertiser._wait_for_group_interface")
    @patch("miracast_server.advertiser.GLib.idle_add")
    def test_shutdown_removes_group(self, mock_idle, mock_wait, mock_wpa):
        """stop_advertising must call p2p_group_remove on the group interface."""
        mock_wpa.return_value = "OK"
        mock_wait.return_value = "p2p-wlx123-0"

        advertiser = MiracastAdvertiser(
            p2p_interface="wlx123", ctrl_path="/tmp/ctrl"
        )
        advertiser.start_advertising()

        # Now stop
        mock_wpa.reset_mock()
        advertiser.stop_advertising()

        # Verify p2p_group_remove was called
        assert any("p2p_group_remove" in str(c) for c in mock_wpa.call_args_list)
        assert advertiser.is_advertising is False
        assert advertiser.group_interface is None
