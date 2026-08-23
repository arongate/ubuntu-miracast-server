"""Tests for MiracastAdvertiser — Autonomous GO mode."""

from unittest.mock import MagicMock, patch, call
import pytest

from miracast_server.advertiser import (
    MiracastAdvertiser,
    _encode_wfd_device_info,
    _WFD_ASSOCIATED_BSSID_SUBELEMENT,
    _WFD_COUPLED_SINK_SUBELEMENT,
)


class TestWFDSubelementEncoding:
    """Test WFD Device Info subelement generation."""

    def test_default_port(self):
        result = _encode_wfd_device_info(7236)
        # Port 7236 = 0x1C44
        assert "1C44" in result
        # Device info = 0x0011 (Sink + Session Available)
        assert "0011" in result

    def test_custom_port(self):
        result = _encode_wfd_device_info(8000)
        # Port 8000 = 0x1F40
        assert "1F40" in result

    def test_format_is_16_hex_chars(self):
        result = _encode_wfd_device_info(7236)
        # Format: 0006 + DeviceInfo(4) + Port(4) + Throughput(4) = 16 chars
        assert len(result) == 16
        assert all(c in "0123456789ABCDEF" for c in result)


class TestMiracastAdvertiserInit:
    """Test advertiser initialization."""

    def test_defaults(self):
        adv = MiracastAdvertiser()
        assert adv._device_name == "Ubuntu Miracast Server"
        assert adv._rtsp_port == 7236
        assert adv.is_advertising is False
        assert adv.group_interface is None

    def test_custom_params(self):
        adv = MiracastAdvertiser(
            device_name="My Sink",
            rtsp_port=8000,
            p2p_interface="wlx123",
            ctrl_path="/tmp/test",
        )
        assert adv._device_name == "My Sink"
        assert adv._rtsp_port == 8000
        assert adv.p2p_interface == "wlx123"
        assert adv.ctrl_path == "/tmp/test"


class TestMiracastAdvertiserStartStop:
    """Test the start/stop advertising lifecycle."""

    @patch("miracast_server.advertiser._run_wpa_cli")
    @patch("miracast_server.advertiser.MiracastAdvertiser._wait_for_group_interface")
    def test_start_advertising_issues_correct_commands(self, mock_wait, mock_wpa):
        """Verify p2p_group_add is issued with correct WFD setup."""
        mock_wpa.return_value = "OK"
        mock_wait.return_value = "p2p-wlx-0"

        adv = MiracastAdvertiser(
            device_name="Test Sink",
            rtsp_port=7236,
            p2p_interface="wlx123",
            ctrl_path="/tmp/ctrl",
        )
        # Suppress GLib.idle_add (no main loop in tests)
        with patch("miracast_server.advertiser.GLib.idle_add"):
            adv.start_advertising()

        # Verify WFD commands were issued in correct order
        calls = mock_wpa.call_args_list
        cmds = [(c[0][1] if len(c[0]) > 1 else c[0][0]) for c in calls]

        # Must set wifi_display, subelements, device_name, device_type, then p2p_group_add
        assert any("wifi_display" in str(c) for c in calls)
        assert any("wfd_subelem_set" in str(c) for c in calls)
        assert any("p2p_group_add" in str(c) for c in calls)

        # Verify state
        assert adv.is_advertising is True
        assert adv.group_interface == "p2p-wlx-0"

    @patch("miracast_server.advertiser._run_wpa_cli")
    @patch("miracast_server.advertiser.MiracastAdvertiser._wait_for_group_interface")
    def test_start_advertising_idempotent(self, mock_wait, mock_wpa):
        """Calling start twice should not create two groups."""
        mock_wpa.return_value = "OK"
        mock_wait.return_value = "p2p-wlx-0"

        adv = MiracastAdvertiser(p2p_interface="wlx123", ctrl_path="/tmp/ctrl")
        with patch("miracast_server.advertiser.GLib.idle_add"):
            adv.start_advertising()
            call_count_after_first = mock_wpa.call_count
            adv.start_advertising()  # Should be ignored
            assert mock_wpa.call_count == call_count_after_first

    @patch("miracast_server.advertiser._run_wpa_cli")
    @patch("miracast_server.advertiser.MiracastAdvertiser._wait_for_group_interface")
    def test_start_advertising_failure_emits_error(self, mock_wait, mock_wpa):
        """If p2p_group_add fails, advertising-error should be emitted."""
        mock_wpa.return_value = "FAIL"

        adv = MiracastAdvertiser(p2p_interface="wlx123", ctrl_path="/tmp/ctrl")
        errors = []
        with patch("miracast_server.advertiser.GLib.idle_add", side_effect=lambda *a: errors.append(a)):
            adv.start_advertising()

        assert adv.is_advertising is False
        # Should have emitted advertising-error
        assert any("advertising-error" in str(e) for e in errors)

    @patch("miracast_server.advertiser._run_wpa_cli")
    @patch("miracast_server.advertiser.MiracastAdvertiser._wait_for_group_interface")
    def test_stop_advertising_removes_group(self, mock_wait, mock_wpa):
        """stop_advertising should call p2p_group_remove."""
        mock_wpa.return_value = "OK"
        mock_wait.return_value = "p2p-wlx-0"

        adv = MiracastAdvertiser(p2p_interface="wlx123", ctrl_path="/tmp/ctrl")
        with patch("miracast_server.advertiser.GLib.idle_add"):
            adv.start_advertising()
            mock_wpa.reset_mock()
            adv.stop_advertising()

        # Must have called p2p_group_remove with the group interface
        assert any("p2p_group_remove" in str(c) for c in mock_wpa.call_args_list)
        assert adv.is_advertising is False
        assert adv.group_interface is None

    @patch("miracast_server.advertiser._run_wpa_cli")
    @patch("miracast_server.advertiser.MiracastAdvertiser._wait_for_group_interface")
    def test_ctrl_path_passed_to_wpa_cli(self, mock_wait, mock_wpa):
        """All wpa_cli calls must use the ctrl_path."""
        mock_wpa.return_value = "OK"
        mock_wait.return_value = "p2p-wlx-0"

        adv = MiracastAdvertiser(p2p_interface="wlx123", ctrl_path="/tmp/my-ctrl")
        with patch("miracast_server.advertiser.GLib.idle_add"):
            adv.start_advertising()

        # Every call should have ctrl_path="/tmp/my-ctrl"
        for c in mock_wpa.call_args_list:
            assert c.kwargs.get("ctrl_path") == "/tmp/my-ctrl"

    @patch("miracast_server.advertiser._run_wpa_cli")
    @patch("miracast_server.advertiser.MiracastAdvertiser._wait_for_group_interface")
    def test_group_interface_timeout_emits_error(self, mock_wait, mock_wpa):
        """If group interface never appears, emit error."""
        mock_wpa.return_value = "OK"
        mock_wait.return_value = None  # Timeout

        adv = MiracastAdvertiser(p2p_interface="wlx123", ctrl_path="/tmp/ctrl")
        errors = []
        with patch("miracast_server.advertiser.GLib.idle_add", side_effect=lambda *a: errors.append(a)):
            adv.start_advertising()

        assert adv.is_advertising is False
        assert any("did not appear" in str(e) for e in errors)
