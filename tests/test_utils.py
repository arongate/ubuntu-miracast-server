"""Tests for the miracast_server.utils module."""

from unittest.mock import MagicMock, patch

import pytest

from miracast_server.utils import _find_p2p_interface, _run_wpa_cli, _validate_wpa_param


class TestValidateWpaParam:
    """Tests for _validate_wpa_param."""

    def test_valid_alphanumeric(self):
        assert _validate_wpa_param("wlan0") is True

    def test_valid_with_colons(self):
        assert _validate_wpa_param("AA:BB:CC:DD:EE:FF") is True

    def test_valid_with_hyphens(self):
        assert _validate_wpa_param("p2p-dev-wlan0") is True

    def test_valid_with_underscores(self):
        assert _validate_wpa_param("wifi_display") is True

    def test_valid_mixed(self):
        assert _validate_wpa_param("p2p-dev_wlan0:iface") is True

    def test_invalid_space(self):
        assert _validate_wpa_param("wlan 0") is False

    def test_invalid_semicolon(self):
        assert _validate_wpa_param("wlan0;rm -rf /") is False

    def test_invalid_pipe(self):
        assert _validate_wpa_param("wlan0|cat") is False

    def test_invalid_dollar(self):
        assert _validate_wpa_param("$HOME") is False

    def test_invalid_backtick(self):
        assert _validate_wpa_param("`whoami`") is False

    def test_invalid_ampersand(self):
        assert _validate_wpa_param("wlan0&") is False

    def test_invalid_slash(self):
        assert _validate_wpa_param("/etc/passwd") is False

    def test_invalid_equals(self):
        assert _validate_wpa_param("key=value") is False

    def test_empty_string(self):
        assert _validate_wpa_param("") is False

    def test_numeric_only(self):
        assert _validate_wpa_param("12345") is True

    def test_single_char(self):
        assert _validate_wpa_param("a") is True

    def test_all_allowed_chars(self):
        assert _validate_wpa_param("aZ0-_:") is True


class TestFindP2pInterface:
    """Tests for _find_p2p_interface."""

    @patch("miracast_server.utils.subprocess.run")
    def test_finds_p2p_interface(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Available interfaces:\np2p-dev-wlo1\nwlo1\n",
        )
        p2p_iface, wifi_iface = _find_p2p_interface()
        assert p2p_iface == "p2p-dev-wlo1"
        assert wifi_iface == "wlo1"

    @patch("miracast_server.utils.subprocess.run")
    def test_no_p2p_interface_raises(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Available interfaces:\nwlo1\n",
        )
        with pytest.raises(RuntimeError, match="No P2P-capable interface"):
            _find_p2p_interface()

    @patch("miracast_server.utils.subprocess.run")
    def test_wpa_cli_failure_raises(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        with pytest.raises(RuntimeError, match="non-zero exit code"):
            _find_p2p_interface()

    @patch("miracast_server.utils.subprocess.run")
    def test_timeout_raises(self, mock_run):
        from subprocess import TimeoutExpired

        mock_run.side_effect = TimeoutExpired(cmd="wpa_cli", timeout=5)
        with pytest.raises(RuntimeError, match="Timeout"):
            _find_p2p_interface()

    @patch("miracast_server.utils.subprocess.run")
    def test_os_error_raises(self, mock_run):
        mock_run.side_effect = OSError("No such file or directory")
        with pytest.raises(RuntimeError, match="Failed to execute wpa_cli"):
            _find_p2p_interface()

    @patch("miracast_server.utils.subprocess.run")
    def test_uses_list_format_no_shell(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Available interfaces:\np2p-dev-wlo1\nwlo1\n",
        )
        _find_p2p_interface()
        call_args = mock_run.call_args
        # Verify it's called with a list, not a string
        assert isinstance(call_args[0][0], list)
        # Verify shell is not passed as True
        assert call_args[1].get("shell", False) is False


class TestRunWpaCli:
    """Tests for _run_wpa_cli."""

    @patch("miracast_server.utils.subprocess.run")
    def test_successful_command(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="OK\n",
        )
        result = _run_wpa_cli("p2p-dev-wlo1", "p2p_listen")
        assert result == "OK"

    @patch("miracast_server.utils.subprocess.run")
    def test_command_with_multiple_args(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="OK\n",
        )
        _run_wpa_cli("p2p-dev-wlo1", "set", "wifi_display", "1")
        cmd = mock_run.call_args[0][0]
        assert cmd == ["sudo", "wpa_cli", "-i", "p2p-dev-wlo1", "set", "wifi_display", "1"]

    @patch("miracast_server.utils.subprocess.run")
    def test_invalid_interface_raises(self, mock_run):
        with pytest.raises(ValueError, match="Invalid interface name"):
            _run_wpa_cli("wlan0; rm -rf /", "p2p_listen")
        mock_run.assert_not_called()

    @patch("miracast_server.utils.subprocess.run")
    def test_invalid_arg_raises(self, mock_run):
        with pytest.raises(ValueError, match="Invalid wpa_cli parameter"):
            _run_wpa_cli("p2p-dev-wlo1", "set$(whoami)")
        mock_run.assert_not_called()

    @patch("miracast_server.utils.subprocess.run")
    def test_command_failure_raises(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="FAIL\n",
            stderr="",
        )
        with pytest.raises(RuntimeError, match="wpa_cli command failed"):
            _run_wpa_cli("p2p-dev-wlo1", "p2p_listen")

    @patch("miracast_server.utils.subprocess.run")
    def test_timeout_raises(self, mock_run):
        from subprocess import TimeoutExpired

        mock_run.side_effect = TimeoutExpired(cmd="wpa_cli", timeout=10)
        with pytest.raises(RuntimeError, match="timed out"):
            _run_wpa_cli("p2p-dev-wlo1", "p2p_listen")

    @patch("miracast_server.utils.subprocess.run")
    def test_os_error_raises(self, mock_run):
        mock_run.side_effect = OSError("Permission denied")
        with pytest.raises(RuntimeError, match="Failed to execute wpa_cli"):
            _run_wpa_cli("p2p-dev-wlo1", "p2p_listen")

    @patch("miracast_server.utils.subprocess.run")
    def test_uses_list_format_no_shell(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="OK\n")
        _run_wpa_cli("p2p-dev-wlo1", "p2p_listen")
        call_args = mock_run.call_args
        assert isinstance(call_args[0][0], list)
        assert call_args[1].get("shell", False) is False

    @patch("miracast_server.utils.subprocess.run")
    def test_mac_address_arg_is_valid(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="OK\n")
        result = _run_wpa_cli("p2p-dev-wlo1", "p2p_connect", "AA:BB:CC:DD:EE:FF", "pbc")
        assert result == "OK"

    @patch("miracast_server.utils.subprocess.run")
    def test_validates_all_args_before_executing(self, mock_run):
        """Ensure no subprocess call is made if any arg is invalid."""
        with pytest.raises(ValueError):
            _run_wpa_cli("p2p-dev-wlo1", "valid_arg", "invalid arg")
        mock_run.assert_not_called()
