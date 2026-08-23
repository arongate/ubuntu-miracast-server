"""Tests for ConnectionHandler — Autonomous GO WPS PIN flow."""

from unittest.mock import MagicMock, patch, call
from datetime import datetime
import pytest

from miracast_server.connection import ConnectionHandler, _generate_pin


class TestPinGeneration:
    """Test WPS PIN generation."""

    def test_pin_is_8_digits(self):
        pin = _generate_pin()
        assert len(pin) == 8
        assert pin.isdigit()

    def test_pin_is_random(self):
        pins = {_generate_pin() for _ in range(100)}
        # Should have many unique values (not all the same)
        assert len(pins) > 50


class TestConnectionHandlerInit:
    """Test connection handler initialization."""

    def test_defaults(self):
        handler = ConnectionHandler()
        assert handler.is_listening is False
        assert handler.active_connection is None
        assert handler._current_pin is None

    def test_custom_params(self):
        handler = ConnectionHandler(
            p2p_interface="wlx123",
            connection_timeout=60,
        )
        assert handler._p2p_interface == "wlx123"
        assert handler._connection_timeout == 60


class TestConnectionHandlerWPSArming:
    """Test WPS PIN arming on the group interface."""

    @patch("miracast_server.connection._run_wpa_cli")
    @patch("miracast_server.connection.GLib.idle_add")
    def test_start_listening_arms_wps_pin(self, mock_idle, mock_wpa):
        """start_listening must call wps_pin any <PIN> on the group interface."""
        mock_wpa.return_value = "OK"

        handler = ConnectionHandler(p2p_interface="wlx123")
        handler._ctrl_path = "/tmp/ctrl"

        # Mock the thread to not actually start
        with patch("threading.Thread") as mock_thread:
            mock_thread.return_value.start = MagicMock()
            handler.start_listening("p2p-wlx123-0")

        # Verify wps_pin was called on the GROUP interface
        mock_wpa.assert_called_once()
        args = mock_wpa.call_args
        assert args[0][0] == "p2p-wlx123-0"  # GROUP interface
        assert args[0][1] == "wps_pin"
        assert args[0][2] == "any"
        assert len(args[0][3]) == 8  # PIN
        assert args.kwargs["ctrl_path"] == "/tmp/ctrl"

    @patch("miracast_server.connection._run_wpa_cli")
    @patch("miracast_server.connection.GLib.idle_add")
    def test_start_listening_emits_pin_display(self, mock_idle, mock_wpa):
        """start_listening must emit pin-display signal with the PIN."""
        mock_wpa.return_value = "OK"

        handler = ConnectionHandler(p2p_interface="wlx123")
        handler._ctrl_path = "/tmp/ctrl"

        with patch("threading.Thread") as mock_thread:
            mock_thread.return_value.start = MagicMock()
            handler.start_listening("p2p-wlx123-0")

        # Verify pin-display was emitted via GLib.idle_add
        pin_calls = [c for c in mock_idle.call_args_list if "pin-display" in str(c)]
        assert len(pin_calls) == 1

    @patch("miracast_server.connection._run_wpa_cli")
    @patch("miracast_server.connection.GLib.idle_add")
    def test_rearm_wps_pin_generates_new_pin(self, mock_idle, mock_wpa):
        """rearm_wps_pin must generate a fresh PIN and re-arm."""
        mock_wpa.return_value = "OK"

        handler = ConnectionHandler(p2p_interface="wlx123")
        handler._ctrl_path = "/tmp/ctrl"
        handler._group_interface = "p2p-wlx123-0"
        handler._current_pin = "12345678"

        handler.rearm_wps_pin()

        # PIN should be different
        assert handler._current_pin != "12345678"
        assert len(handler._current_pin) == 8

        # wps_pin should have been called with the new PIN
        mock_wpa.assert_called_once()
        assert mock_wpa.call_args[0][3] == handler._current_pin


class TestConnectionHandlerEventProcessing:
    """Test AP-STA-CONNECTED event handling."""

    @patch("miracast_server.connection.ConnectionHandler._wait_for_dhcp_lease")
    @patch("miracast_server.connection.GLib.idle_add")
    def test_handle_sta_connected_creates_connection(self, mock_idle, mock_wait_dhcp):
        """AP-STA-CONNECTED must create an IncomingConnection and emit signal."""
        mock_wait_dhcp.return_value = "192.168.173.80"

        handler = ConnectionHandler(p2p_interface="wlx123")
        handler._group_interface = "p2p-wlx123-0"

        handler._handle_sta_connected("aa:bb:cc:dd:ee:ff")

        # Should have an active connection
        assert handler.active_connection is not None
        assert handler.active_connection.peer_address == "aa:bb:cc:dd:ee:ff"
        assert handler.active_connection.peer_ip == "192.168.173.80"
        assert handler.active_connection.our_ip == "192.168.173.1"
        assert handler.active_connection.go_role is True
        assert handler.active_connection.group_interface == "p2p-wlx123-0"

        # Should have emitted connection-received
        emit_calls = [c for c in mock_idle.call_args_list if "connection-received" in str(c)]
        assert len(emit_calls) == 1

    @patch("miracast_server.connection._run_wpa_cli")
    @patch("miracast_server.connection.GLib.idle_add")
    def test_handle_sta_disconnected_emits_lost_and_rearms(self, mock_idle, mock_wpa):
        """AP-STA-DISCONNECTED must emit connection-lost and re-arm WPS."""
        mock_wpa.return_value = "OK"

        handler = ConnectionHandler(p2p_interface="wlx123")
        handler._group_interface = "p2p-wlx123-0"
        handler._ctrl_path = "/tmp/ctrl"
        handler._current_pin = "12345678"

        # Simulate an active connection
        from miracast_server.models import IncomingConnection
        handler._active_connection = IncomingConnection(
            peer_address="aa:bb:cc:dd:ee:ff",
            peer_ip="192.168.49.10",
            peer_name="Test",
            group_interface="p2p-wlx123-0",
            our_ip="192.168.49.1",
            connected_at=datetime.now(),
            go_role=True,
        )

        handler._handle_sta_disconnected()

        # Connection should be cleared
        assert handler.active_connection is None

        # Should have emitted connection-lost
        lost_calls = [c for c in mock_idle.call_args_list if "connection-lost" in str(c)]
        assert len(lost_calls) == 1

        # Should have re-armed WPS with a NEW pin
        assert handler._current_pin != "12345678"
        assert mock_wpa.called


class TestConnectionHandlerDHCP:
    """Test DHCP setup on group interface."""

    @patch("subprocess.Popen")
    @patch("subprocess.run")
    def test_setup_dhcp_assigns_ip_and_starts_dnsmasq(self, mock_run, mock_popen):
        """DHCP setup must assign static IP and start dnsmasq."""
        mock_run.return_value = MagicMock(returncode=0)

        handler = ConnectionHandler()
        handler._group_interface = "p2p-wlx123-0"

        ip = handler._setup_dhcp()

        assert ip == "192.168.173.1"

        # Must have called ip addr add
        ip_calls = [c for c in mock_run.call_args_list if "addr" in str(c) and "add" in str(c)]
        assert len(ip_calls) >= 1

        # Must have started dnsmasq
        assert mock_popen.called
        dnsmasq_cmd = mock_popen.call_args[0][0]
        assert "dnsmasq" in dnsmasq_cmd
        assert "--interface=p2p-wlx123-0" in dnsmasq_cmd


class TestConnectionHandlerIntegrationFlow:
    """Integration test: full flow from start_listening through connection."""

    @patch("miracast_server.connection.ConnectionHandler._wait_for_dhcp_lease")
    @patch("miracast_server.connection._run_wpa_cli")
    @patch("miracast_server.connection.GLib.idle_add")
    def test_full_flow_pin_to_connection(self, mock_idle, mock_wpa, mock_wait_dhcp):
        """Simulate the complete flow: arm PIN → source connects → connection-received."""
        mock_wpa.return_value = "OK"
        mock_wait_dhcp.return_value = "192.168.173.80"

        handler = ConnectionHandler(p2p_interface="wlx123")
        handler._ctrl_path = "/tmp/ctrl"

        # Step 1: Start listening (arms PIN)
        with patch("threading.Thread") as mock_thread:
            mock_thread.return_value.start = MagicMock()
            handler.start_listening("p2p-wlx123-0")

        assert handler._current_pin is not None
        assert handler.is_listening is True

        # Step 2: Simulate AP-STA-CONNECTED event
        handler._handle_sta_connected("be:10:7b:d4:5f:b8")

        # Step 3: Verify connection was established
        conn = handler.active_connection
        assert conn is not None
        assert conn.peer_address == "be:10:7b:d4:5f:b8"
        assert conn.peer_ip == "192.168.173.80"
        assert conn.our_ip == "192.168.173.1"
        assert conn.go_role is True

        # Step 4: Simulate disconnect
        handler._handle_sta_disconnected()
        assert handler.active_connection is None

        # Step 5: WPS should be re-armed with new PIN
        assert mock_wpa.call_count >= 2  # Initial + re-arm
