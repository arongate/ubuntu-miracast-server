"""Main application entry point for Ubuntu Miracast Server.

Bootstraps the GTK/Adw application, instantiates core components,
and wires them together via GObject signals.
"""

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
from gi.repository import Adw, Gio, GLib, Gst

from miracast_server.advertiser import MiracastAdvertiser
from miracast_server.config import ServerConfig
from miracast_server.connection import ConnectionHandler
from miracast_server.history import ServerSessionHistory
from miracast_server.models import SourceInfo
from miracast_server.receiver import MiracastReceiver

# Configure logging
log_dir = Path.home() / ".local" / "share" / "ubuntu-miracast-server" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "miracast-server.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
)

logger = logging.getLogger(__name__)

# Initialize GStreamer
Gst.init(None)


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Ubuntu Miracast Server — receive wireless display streams"
    )
    parser.add_argument(
        "--service",
        action="store_true",
        help="Run in headless service mode (no GUI)",
    )
    parser.add_argument(
        "--fullscreen",
        action="store_true",
        help="Start in fullscreen mode",
    )
    parser.add_argument(
        "--interface",
        type=str,
        default=None,
        help="P2P device interface to use (e.g., p2p-dev-wlx3c78950c6ede). Auto-detected if not specified.",
    )
    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Override the advertised device name",
    )
    return parser.parse_args()


class MiracastServerApp(Adw.Application):
    """Main Miracast Server application.

    Manages the lifecycle of all core components and wires them together
    via GObject signal connections.
    """

    def __init__(self, device_name: str | None = None, start_fullscreen: bool = False,
                 p2p_interface: str | None = None):
        """Initialize the application.

        Args:
            device_name: Override device name (from CLI --name flag).
            start_fullscreen: Whether to start the window in fullscreen mode.
            p2p_interface: Override P2P interface (from CLI --interface flag or config).
        """
        super().__init__(
            application_id="com.ubuntu.miracast-server",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self._device_name_override = device_name
        self._start_fullscreen = start_fullscreen
        self._p2p_interface_override = p2p_interface
        self._shutting_down = False

        # Core components (initialized on activate)
        self.config: ServerConfig | None = None
        self.history: ServerSessionHistory | None = None
        self.advertiser: MiracastAdvertiser | None = None
        self.connection_handler: ConnectionHandler | None = None
        self.receiver: MiracastReceiver | None = None

        self.connect("activate", self._on_activate)
        self.connect("shutdown", self._on_shutdown)

    def _on_activate(self, app) -> None:
        """Handle application activation — create components and window."""
        # Initialize core components
        self.config = ServerConfig()
        self.history = ServerSessionHistory()

        device_name = self._device_name_override or self.config.get(
            "general", "device_name", "Ubuntu Miracast Server"
        )
        rtsp_port = self.config.get("streaming", "rtsp_port", 7236)
        rtp_port = self.config.get("network", "rtp_port", 1028)
        go_intent = self.config.get("network", "go_intent", 15)
        auto_accept = self.config.get("network", "auto_accept", True)
        connection_timeout = self.config.get("network", "connection_timeout", 30)
        audio_enabled = self.config.get("streaming", "audio_enabled", True)

        # Determine P2P interface: CLI flag > config > auto-detect
        p2p_interface = (
            self._p2p_interface_override
            or self.config.get("network", "p2p_interface", "")
            or None
        )

        self.advertiser = MiracastAdvertiser(
            device_name=device_name,
            rtsp_port=rtsp_port,
            p2p_interface=p2p_interface,
        )

        self.receiver = MiracastReceiver(
            rtsp_port=rtsp_port,
            rtp_port=rtp_port,
            headless=False,
            audio_enabled=audio_enabled,
        )

        # Create connection handler (uses placeholder interface, updated when advertiser starts)
        self._get_or_create_connection_handler(go_intent, auto_accept, connection_timeout)

        # Wire signals between components
        self._wire_signals()

        # Create main window
        from miracast_server.ui.main_window import MainWindow

        # ConnectionHandler needs the p2p_interface — defer until advertiser starts
        self.advertiser.connect("advertising-started", self._on_advertiser_started)

        win = MainWindow(
            application=app,
            advertiser=self.advertiser,
            connection_handler=self.connection_handler,
            receiver=self.receiver,
            history=self.history,
            config=self.config,
        )
        win.present()

        # FR-UI11: Start in fullscreen if --fullscreen CLI flag was passed
        if self._start_fullscreen:
            win.fullscreen()

        # Start advertising
        self.advertiser.start_advertising()
        logger.info("Application activated")

    def _get_or_create_connection_handler(
        self, go_intent: int, auto_accept: bool, timeout: int
    ) -> ConnectionHandler:
        """Get or create the connection handler.

        Uses a placeholder interface that gets updated once the advertiser
        detects the real P2P interface.
        """
        if self.connection_handler is None:
            # Use a default interface name — will be updated
            self.connection_handler = ConnectionHandler(
                p2p_interface="p2p-dev-wlan0",
                go_intent=go_intent,
                auto_accept=auto_accept,
                connection_timeout=timeout,
            )
        return self.connection_handler

    def _on_advertiser_started(self, advertiser) -> None:
        """Once advertising starts, update connection handler with real interface."""
        if advertiser.p2p_interface and self.connection_handler:
            self.connection_handler._p2p_interface = advertiser.p2p_interface
            self.connection_handler.start_listening()
            logger.info("Connection handler started on %s", advertiser.p2p_interface)

    def _wire_signals(self) -> None:
        """Wire GObject signals between core components for functional flow.

        Signal chain:
          ConnectionHandler.connection-received → Receiver.start_receiving
          ConnectionHandler.connection-error → return to advertising
          Receiver.stream-stopped → History.add_session + return to advertising
          Receiver.stream-error → History.add_session (partial) + return to advertising
        """
        # Connection → Receiver
        self.connection_handler.connect(
            "connection-received", self._on_connection_start_receiving
        )

        # Connection error → return to advertising
        self.connection_handler.connect(
            "connection-error", self._on_connection_error_recovery
        )

        # Stream end → History + return to advertising
        self.receiver.connect("stream-stopped", self._on_stream_ended)
        self.receiver.connect("stream-error", self._on_stream_error_record)

    def _on_connection_start_receiving(self, handler, connection) -> None:
        """Start receiver when a P2P connection is established."""
        if self.receiver.is_receiving:
            logger.warning("Ignoring new connection — already receiving")
            return
        self.receiver.start_receiving(connection)

    def _on_connection_error_recovery(self, handler, error_msg: str) -> None:
        """Return to advertising after a connection error/timeout."""
        logger.info("Connection failed, returning to advertising: %s", error_msg)
        self._return_to_advertising()

    def _on_stream_ended(self, receiver, stats) -> None:
        """Record session and return to advertising after stream ends."""
        if self.history and receiver.source_info:
            self.history.add_session(receiver.source_info, stats)
        # Return to advertising/listening state
        self._return_to_advertising()

    def _on_stream_error_record(self, receiver, error_msg: str) -> None:
        """Record partial session on error and return to advertising."""
        if self.history and receiver.source_info:
            stats = receiver._build_stats()
            self.history.add_session(receiver.source_info, stats)
        self._return_to_advertising()

    def _return_to_advertising(self) -> None:
        """Return to advertising/listening state after stream ends or connection error."""
        if self._shutting_down:
            return
        # Always restart advertising to ensure we're discoverable again
        if self.advertiser:
            if self.advertiser.is_advertising:
                # Already advertising but may have left P2P listen — re-enter
                try:
                    from miracast_server.utils import _run_wpa_cli
                    _run_wpa_cli(self.advertiser.p2p_interface, "p2p_listen")
                    logger.info("Re-entered P2P listen state")
                except Exception as e:
                    logger.debug("p2p_listen re-entry: %s", e)
            else:
                self.advertiser.start_advertising()

    def switch_interface(self, new_interface: str) -> None:
        """Switch the P2P interface at runtime.

        Stops advertising on the current interface, updates the interface,
        and restarts advertising on the new one.

        Args:
            new_interface: The new P2P device interface name (e.g., 'p2p-dev-wlx3c78950c6ede').
        """
        if not new_interface:
            logger.warning("switch_interface called with empty interface")
            return

        logger.info("Switching P2P interface to: %s", new_interface)

        # Stop current advertising and listening
        if self.advertiser and self.advertiser.is_advertising:
            self.advertiser.stop_advertising()
        if self.connection_handler and self.connection_handler.is_listening:
            self.connection_handler.stop_listening()

        # Update the interface on both components
        self.advertiser._p2p_interface = new_interface
        self.connection_handler._p2p_interface = new_interface

        # Save to config
        if self.config:
            self.config.set("network", "p2p_interface", new_interface)

        # Restart advertising
        self.advertiser.start_advertising()
        logger.info("Interface switched to %s — restarting advertising", new_interface)

    def _on_shutdown(self, app) -> None:
        """Handle application shutdown — orderly cleanup."""
        self._graceful_shutdown()

    def _graceful_shutdown(self) -> None:
        """Perform graceful shutdown: Receiver → ConnectionHandler → Advertiser."""
        if self._shutting_down:
            return
        self._shutting_down = True
        logger.info("Initiating graceful shutdown...")

        # 1. Stop receiver
        if self.receiver and self.receiver.is_receiving:
            try:
                stats = self.receiver.stop_receiving()
                # Record partial session
                if self.history and self.receiver.source_info:
                    self.history.add_session(self.receiver.source_info, stats)
            except Exception as e:
                logger.error("Error stopping receiver: %s", e)

        # 2. Stop connection handler
        if self.connection_handler:
            try:
                self.connection_handler.disconnect_peer()
                self.connection_handler.stop_listening()
            except Exception as e:
                logger.error("Error stopping connection handler: %s", e)

        # 3. Stop advertiser
        if self.advertiser:
            try:
                self.advertiser.stop_advertising()
            except Exception as e:
                logger.error("Error stopping advertiser: %s", e)

        logger.info("Graceful shutdown complete")


def main() -> int:
    """Run the Ubuntu Miracast Server application."""
    args = _parse_args()

    if args.service:
        from miracast_server.service import run_as_service
        return run_as_service(device_name=args.name, p2p_interface=args.interface)

    # Set up signal handling for graceful shutdown
    app = MiracastServerApp(
        device_name=args.name,
        start_fullscreen=args.fullscreen,
        p2p_interface=args.interface,
    )

    # Handle SIGTERM/SIGINT
    def signal_handler(sig, frame):
        logger.info("Received signal %s, shutting down...", sig)
        app._graceful_shutdown()
        app.quit()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    return app.run(sys.argv[:1])  # Don't pass args twice


if __name__ == "__main__":
    sys.exit(main())
