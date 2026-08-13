"""Service management for Ubuntu Miracast Server.

Implements systemd user service installation, lifecycle management,
and headless (service) mode operation.
"""

import logging
import os
import subprocess
import time
from pathlib import Path

import gi

gi.require_version("GLib", "2.0")
gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst

from miracast_server.advertiser import MiracastAdvertiser
from miracast_server.config import ServerConfig
from miracast_server.connection import ConnectionHandler
from miracast_server.history import ServerSessionHistory
from miracast_server.models import SourceInfo
from miracast_server.receiver import MiracastReceiver

logger = logging.getLogger(__name__)

_SERVICE_NAME = "ubuntu-miracast-server.service"

_SERVICE_TEMPLATE = """\
[Unit]
Description=Ubuntu Miracast Server (Wi-Fi Display Sink)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/ubuntu-miracast-server --service
Restart=on-failure
RestartSec=5
Environment=DISPLAY=:0

[Install]
WantedBy=default.target
"""


class ServerServiceManager:
    """Manages the systemd user service for headless Miracast receiving.

    Provides install, enable, disable, start, stop operations with
    rollback on failure to avoid inconsistent state.
    """

    def __init__(self):
        """Initialize the service manager."""
        self._service_dir = Path.home() / ".config" / "systemd" / "user"
        self._service_path = self._service_dir / _SERVICE_NAME

    @property
    def is_installed(self) -> bool:
        """Whether the service file exists."""
        return self._service_path.exists()

    @property
    def is_enabled(self) -> bool:
        """Whether the service is enabled to start on login."""
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-enabled", _SERVICE_NAME],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip() == "enabled"
        except (subprocess.TimeoutExpired, OSError):
            return False

    @property
    def is_running(self) -> bool:
        """Whether the service is currently active."""
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", _SERVICE_NAME],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip() == "active"
        except (subprocess.TimeoutExpired, OSError):
            return False

    def install(self) -> None:
        """Install the service file and reload systemd.

        Implements rollback: if daemon-reload fails, the service file is removed.

        Raises:
            RuntimeError: If installation fails.
        """
        # Create directory
        self._service_dir.mkdir(parents=True, exist_ok=True)

        # Write service file
        try:
            self._service_path.write_text(_SERVICE_TEMPLATE)
        except OSError as e:
            raise RuntimeError(f"Failed to write service file: {e}") from e

        # Reload systemd — rollback on failure
        try:
            self._daemon_reload()
        except RuntimeError:
            # Rollback: remove the file we just wrote
            try:
                self._service_path.unlink()
            except OSError:
                pass
            raise

        logger.info("Service installed at %s", self._service_path)

    def uninstall(self) -> None:
        """Remove the service file and reload systemd.

        Stops and disables the service first if it's active.

        Raises:
            RuntimeError: If uninstallation fails.
        """
        if self.is_running:
            self.stop()
        if self.is_enabled:
            self.disable()

        if self._service_path.exists():
            try:
                self._service_path.unlink()
            except OSError as e:
                raise RuntimeError(f"Failed to remove service file: {e}") from e

        try:
            self._daemon_reload()
        except RuntimeError as e:
            logger.warning("daemon-reload after uninstall failed: %s", e)

        logger.info("Service uninstalled")

    def enable(self) -> None:
        """Enable the service to start on user login.

        Raises:
            RuntimeError: If enabling fails.
        """
        if not self.is_installed:
            self.install()

        try:
            result = subprocess.run(
                ["systemctl", "--user", "enable", _SERVICE_NAME],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"systemctl enable failed: {result.stderr.strip()}"
                )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("Timeout enabling service") from e
        except OSError as e:
            raise RuntimeError(f"Failed to enable service: {e}") from e

        logger.info("Service enabled")

    def disable(self) -> None:
        """Disable the service from starting on login.

        Raises:
            RuntimeError: If disabling fails.
        """
        try:
            result = subprocess.run(
                ["systemctl", "--user", "disable", _SERVICE_NAME],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"systemctl disable failed: {result.stderr.strip()}"
                )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("Timeout disabling service") from e
        except OSError as e:
            raise RuntimeError(f"Failed to disable service: {e}") from e

        logger.info("Service disabled")

    def start(self) -> None:
        """Start the service.

        Raises:
            RuntimeError: If starting fails.
        """
        if not self.is_installed:
            self.install()

        try:
            result = subprocess.run(
                ["systemctl", "--user", "start", _SERVICE_NAME],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"systemctl start failed: {result.stderr.strip()}"
                )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("Timeout starting service") from e
        except OSError as e:
            raise RuntimeError(f"Failed to start service: {e}") from e

        logger.info("Service started")

    def stop(self) -> None:
        """Stop the service.

        Raises:
            RuntimeError: If stopping fails.
        """
        try:
            result = subprocess.run(
                ["systemctl", "--user", "stop", _SERVICE_NAME],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"systemctl stop failed: {result.stderr.strip()}"
                )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("Timeout stopping service") from e
        except OSError as e:
            raise RuntimeError(f"Failed to stop service: {e}") from e

        logger.info("Service stopped")

    def _daemon_reload(self) -> None:
        """Reload systemd daemon configuration.

        Raises:
            RuntimeError: If reload fails.
        """
        try:
            result = subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"daemon-reload failed: {result.stderr.strip()}"
                )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("Timeout during daemon-reload") from e
        except OSError as e:
            raise RuntimeError(f"Failed to run daemon-reload: {e}") from e


def run_as_service(device_name: str | None = None, p2p_interface: str | None = None) -> int:
    """Run the Miracast Server in headless service mode.

    Uses a GLib main loop (no GTK) with fakesink video output.
    Implements idle timeout to exit after configured inactivity.

    Args:
        device_name: Override device name from CLI.
        p2p_interface: Override P2P interface from CLI.

    Returns:
        Exit code (0 for clean shutdown).
    """
    Gst.init(None)

    config = ServerConfig()
    history = ServerSessionHistory()

    name = device_name or config.get("general", "device_name", "Ubuntu Miracast Server")
    rtsp_port = config.get("streaming", "rtsp_port", 7236)
    rtp_port = config.get("network", "rtp_port", 1028)
    go_intent = config.get("network", "go_intent", 15)
    auto_accept = config.get("network", "auto_accept", True)
    connection_timeout = config.get("network", "connection_timeout", 30)
    audio_enabled = config.get("streaming", "audio_enabled", True)
    idle_timeout = config.get("service", "idle_timeout", 0)

    # Determine P2P interface: CLI flag > config > auto-detect
    iface = p2p_interface or config.get("network", "p2p_interface", "") or None

    logger.info("Starting service mode as '%s' (RTSP port %d, interface=%s)", name, rtsp_port, iface or "auto")

    advertiser = MiracastAdvertiser(device_name=name, rtsp_port=rtsp_port, p2p_interface=iface)
    receiver = MiracastReceiver(
        rtsp_port=rtsp_port,
        rtp_port=rtp_port,
        headless=True,
        audio_enabled=audio_enabled,
    )

    # Main loop
    loop = GLib.MainLoop()
    last_activity = time.monotonic()
    shutting_down = False

    def on_advertiser_started(adv):
        nonlocal last_activity
        last_activity = time.monotonic()

        # Create and start connection handler
        if adv.p2p_interface:
            handler = ConnectionHandler(
                p2p_interface=adv.p2p_interface,
                go_intent=go_intent,
                auto_accept=auto_accept,
                connection_timeout=connection_timeout,
            )

            def on_connection(h, conn):
                nonlocal last_activity
                last_activity = time.monotonic()
                logger.info("Service: connection from %s", conn.peer_name)
                receiver.start_receiving(conn)

            def on_connection_lost(h):
                nonlocal last_activity
                last_activity = time.monotonic()
                logger.info("Service: connection lost")

            def on_stream_stopped(recv, stats):
                nonlocal last_activity
                last_activity = time.monotonic()
                if receiver.source_info:
                    history.add_session(receiver.source_info, stats)
                logger.info("Service: stream stopped")

            def on_stream_error(recv, error):
                nonlocal last_activity
                last_activity = time.monotonic()
                if receiver.source_info:
                    stats = receiver._build_stats()
                    history.add_session(receiver.source_info, stats)
                logger.error("Service: stream error — %s", error)

            handler.connect("connection-received", on_connection)
            handler.connect("connection-lost", on_connection_lost)
            receiver.connect("stream-stopped", on_stream_stopped)
            receiver.connect("stream-error", on_stream_error)
            handler.start_listening()

    advertiser.connect("advertising-started", on_advertiser_started)

    def on_advertiser_error(adv, msg):
        logger.error("Service: advertising error — %s", msg)
        loop.quit()

    advertiser.connect("advertising-error", on_advertiser_error)

    # Idle timeout checker
    def check_idle_timeout():
        if shutting_down:
            return False
        if idle_timeout > 0 and not receiver.is_receiving:
            elapsed = time.monotonic() - last_activity
            if elapsed >= idle_timeout:
                logger.info("Idle timeout reached (%.0fs), exiting", elapsed)
                loop.quit()
                return False
        return True  # Continue checking

    if idle_timeout > 0:
        GLib.timeout_add_seconds(60, check_idle_timeout)

    # Signal handling
    def handle_signal(sig):
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        logger.info("Service received signal %s, shutting down...", sig)

        if receiver.is_receiving:
            stats = receiver.stop_receiving()
            if receiver.source_info:
                history.add_session(receiver.source_info, stats)

        advertiser.stop_advertising()
        loop.quit()

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 2, lambda: handle_signal("SIGINT") or True)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 15, lambda: handle_signal("SIGTERM") or True)

    # Start advertising and enter main loop
    advertiser.start_advertising()

    try:
        loop.run()
    except KeyboardInterrupt:
        handle_signal("KeyboardInterrupt")

    logger.info("Service mode exited")
    return 0
