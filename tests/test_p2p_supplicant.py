"""Tests for P2PSupplicantManager — dedicated wpa_supplicant lifecycle."""

import os
from unittest.mock import MagicMock, patch

import pytest

from miracast_server.p2p_supplicant import _WPA_CONF_TEMPLATE, P2PSupplicantManager


class TestP2PSupplicantManagerInit:
    """Test initialization."""

    def test_defaults(self):
        mgr = P2PSupplicantManager(interface="wlx123")
        assert mgr.interface == "wlx123"
        assert mgr.is_running is False
        assert mgr.ctrl_path == "/tmp/miracast-wpa-p2p"

    def test_custom_device_name(self):
        mgr = P2PSupplicantManager(interface="wlx123", device_name="My Sink")
        assert mgr._device_name == "My Sink"


class TestP2PSupplicantManagerConfig:
    """Test wpa_supplicant config generation."""

    def test_config_template_has_required_fields(self):
        """Config must include ctrl_interface, device_name, P2P settings."""
        config = _WPA_CONF_TEMPLATE.format(ctrl_dir="/tmp/test", device_name="Test")
        assert "ctrl_interface=/tmp/test" in config
        assert "device_name=Test" in config
        assert "device_type=7-0050F204-1" in config
        assert "p2p_go_intent=1" in config
        assert "country=" in config

    @patch("os.chmod")
    def test_write_config_creates_file(self, mock_chmod, tmp_path):
        """_write_config must create a config file."""
        mgr = P2PSupplicantManager(interface="wlx123", device_name="Test")
        mgr._conf_path = str(tmp_path / "test.conf")
        mgr._write_config()

        assert os.path.exists(mgr._conf_path)
        with open(mgr._conf_path) as f:
            content = f.read()
        assert "device_name=Test" in content
        assert "ctrl_interface=" in content


class TestP2PSupplicantManagerLifecycle:
    """Test start/stop lifecycle."""

    @patch("subprocess.run")
    @patch("subprocess.Popen")
    @patch("os.makedirs")
    @patch("os.path.exists")
    def test_start_unmanages_from_nm(self, mock_exists, mock_mkdir, mock_popen, mock_run):
        """Start must call nmcli device set <iface> managed no."""
        mock_exists.return_value = True  # Socket exists
        mock_run.return_value = MagicMock(returncode=0)
        mock_popen.return_value = MagicMock(poll=MagicMock(return_value=None))

        mgr = P2PSupplicantManager(interface="wlx123")
        mgr._conf_path = "/tmp/test.conf"
        mgr._write_config = MagicMock()
        mgr._wait_for_socket = MagicMock(return_value=True)

        mgr.start()

        # Must have called nmcli to unmanage
        nm_calls = [c for c in mock_run.call_args_list if "nmcli" in str(c)]
        assert len(nm_calls) >= 1
        assert "managed" in str(nm_calls[0])
        assert "no" in str(nm_calls[0])

    @patch("subprocess.run")
    @patch("subprocess.Popen")
    @patch("os.makedirs")
    @patch("os.path.exists")
    def test_start_spawns_wpa_supplicant(self, mock_exists, mock_mkdir, mock_popen, mock_run):
        """Start must spawn wpa_supplicant with correct args."""
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        mgr = P2PSupplicantManager(interface="wlx123")
        mgr._write_config = MagicMock()
        mgr._wait_for_socket = MagicMock(return_value=True)

        mgr.start()

        # Must have called Popen with wpa_supplicant
        assert mock_popen.called
        cmd = mock_popen.call_args[0][0]
        assert "wpa_supplicant" in cmd
        assert "-i" in cmd
        assert "wlx123" in cmd
        assert "-D" in cmd
        assert "nl80211" in cmd
        assert mgr.is_running is True

    @patch("subprocess.run")
    def test_stop_kills_process_and_restores_nm(self, mock_run):
        """Stop must kill wpa_supplicant and re-manage with NM."""
        mock_run.return_value = MagicMock(returncode=0)

        mgr = P2PSupplicantManager(interface="wlx123")
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        mock_proc.wait.return_value = 0
        mgr._process = mock_proc
        mgr._started = True
        mgr._was_nm_managed = True

        mgr.stop()

        # Must have killed the process
        kill_calls = [c for c in mock_run.call_args_list if "kill" in str(c)]
        assert len(kill_calls) >= 1

        # Must have restored NM management
        nm_calls = [c for c in mock_run.call_args_list if "nmcli" in str(c)]
        assert len(nm_calls) >= 1
        assert "yes" in str(nm_calls[0])

        assert mgr.is_running is False

    @patch("subprocess.run")
    @patch("subprocess.Popen")
    @patch("os.makedirs")
    @patch("os.path.exists")
    def test_start_failure_restores_nm(self, mock_exists, mock_mkdir, mock_popen, mock_run):
        """If start fails, NM management must be restored."""
        mock_exists.return_value = False  # Socket never appears
        mock_run.return_value = MagicMock(returncode=0)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # Process died
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        mgr = P2PSupplicantManager(interface="wlx123")
        mgr._write_config = MagicMock()

        with pytest.raises(RuntimeError):
            mgr.start()

        # Should have tried to restore NM
        nm_restore_calls = [
            c for c in mock_run.call_args_list if "nmcli" in str(c) and "yes" in str(c)
        ]
        assert len(nm_restore_calls) >= 1
