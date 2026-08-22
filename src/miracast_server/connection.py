"""Wi-Fi Direct Connection Handler for Ubuntu Miracast Server.

Uses the Autonomous GO approach: monitors the GROUP interface for
AP-STA-CONNECTED events after arming WPS PIN. This replaces the
broken GO Negotiation approach.

Flow:
  1. Receive group interface name from advertiser
  2. Generate and display a WPS PIN
  3. Arm the GO's WPS registrar: wps_pin any <PIN>
  4. Wait for AP-STA-CONNECTED event (source connected)
  5. Set up DHCP on the group interface
  6. Emit connection-received with peer details
"""

import logging
import random
import re
import select
import subprocess
import threading
import time
from datetime import datetime

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib, GObject

from miracast_server.models import IncomingConnection
from miracast_server.utils import _run_wpa_cli

logger = logging.getLogger(__name__)

# Event patterns on the GROUP interface
_AP_STA_CONNECTED_PATTERN = re.compile(r"AP-STA-CONNECTED\s+([0-9a-fA-F:]{17})")
_AP_STA_DISCONNECTED_PATTERN = re.compile(r"AP-STA-DISCONNECTED\s+([0-9a-fA-F:]{17})")
_P2P_GROUP_REMOVED_PATTERN = re.compile(r"P2P-GROUP-REMOVED")


def _generate_pin() -> str:
    """Generate an 8-digit WPS PIN."""
    return f"{random.randint(10000000, 99999999)}"


class ConnectionHandler(GObject.Object):
    """Handles Wi-Fi Direct P2P connections via WPS on the Group Owner interface.

    Signals:
      - connection-received(object): Source connected. Payload is IncomingConnection.
      - connection-lost: Source disconnected.
      - connection-error(str): Error during connection handling.
      - pin-display(str, str): PIN to show user. Args: (pin, peer_info).
    """

    __gsignals__ = {
        "connection-received": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "connection-lost": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "connection-error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "pin-display": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }

    def __init__(
        self,
        p2p_interface: str = "",
        go_intent: int = 15,
        auto_accept: bool = True,
        connection_timeout: int = 120,
    ):
        super().__init__()
        self._p2p_interface = p2p_interface
        self._group_interface: str | None = None
        self._ctrl_path: str | None = None
        self._go_intent = go_intent
        self._auto_accept = auto_accept
        self._connection_timeout = connection_timeout

        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._active_connection: IncomingConnection | None = None
        self._current_pin: str | None = None

    @property
    def is_listening(self) -> bool:
        return self._running

    @property
    def active_connection(self) -> IncomingConnection | None:
        with self._lock:
            return self._active_connection

    def start_listening(self, group_interface: str) -> None:
        """Start listening for connections on the P2P group interface.

        Arms WPS PIN and monitors for AP-STA-CONNECTED events.

        Args:
            group_interface: The P2P group interface (e.g., p2p-wlx...-0).
        """
        if self._running:
            logger.debug("Already listening — ignoring")
            return

        self._group_interface = group_interface
        self._running = True

        # Generate and arm WPS PIN
        self._current_pin = _generate_pin()
        self._arm_wps_pin()

        # Emit PIN for display
        GLib.idle_add(self.emit, "pin-display", self._current_pin, "Waiting for source...")

        # Start event monitor on the group interface
        self._thread = threading.Thread(
            target=self._event_monitor_loop,
            name="go-event-monitor",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Listening on %s with PIN %s",
            self._group_interface, self._current_pin,
        )

    def stop_listening(self) -> None:
        """Stop listening for connections."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("Event monitor thread did not stop within 5 seconds")
            self._thread = None
        logger.info("Connection handler stopped")

    def disconnect_peer(self) -> None:
        """Disconnect the current peer."""
        with self._lock:
            self._active_connection = None

    def rearm_wps_pin(self) -> None:
        """Generate a new PIN and re-arm WPS for the next connection."""
        self._current_pin = _generate_pin()
        self._arm_wps_pin()
        GLib.idle_add(self.emit, "pin-display", self._current_pin, "Waiting for source...")
        logger.info("Re-armed WPS with new PIN %s", self._current_pin)

    def _arm_wps_pin(self) -> None:
        """Arm the WPS registrar on the group interface with the current PIN."""
        if not self._group_interface or not self._current_pin:
            return
        try:
            result = _run_wpa_cli(
                self._group_interface, "wps_pin", "any", self._current_pin,
                ctrl_path=self._ctrl_path,
            )
            logger.debug("wps_pin any %s → %s", self._current_pin, result.strip())
        except (RuntimeError, ValueError) as e:
            logger.error("Failed to arm WPS PIN: %s", e)
            GLib.idle_add(self.emit, "connection-error", f"Failed to arm WPS: {e}")

    def _event_monitor_loop(self) -> None:
        """Monitor the GROUP interface for AP-STA-CONNECTED events."""
        logger.info("Event monitor starting on group interface %s", self._group_interface)

        cmd = ["sudo", "wpa_cli"]
        if self._ctrl_path:
            cmd.extend(["-p", self._ctrl_path])
        cmd.extend(["-i", self._group_interface])
        logger.info("Event monitor command: %s", " ".join(cmd))

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as e:
            logger.error("Failed to start wpa_cli: %s", e)
            GLib.idle_add(self.emit, "connection-error", f"Failed to start event monitor: {e}")
            return

        # Wait for process to be ready
        time.sleep(0.5)
        if proc.poll() is not None:
            stderr = proc.stderr.read() if proc.stderr else ""
            logger.error("wpa_cli exited immediately: %s", stderr.strip())
            GLib.idle_add(self.emit, "connection-error", f"wpa_cli failed: {stderr.strip()}")
            return

        try:
            # Drain banner
            self._drain_banner(proc)

            # Send ATTACH
            proc.stdin.write("ATTACH\n")
            proc.stdin.flush()
            time.sleep(0.5)

            # Drain ATTACH response
            self._drain_output(proc, timeout=1.0)

            logger.info("Event monitor attached to %s — waiting for connections", self._group_interface)

            # Main event loop
            while self._running:
                ready, _, _ = select.select([proc.stdout], [], [], 1.0)
                if not ready:
                    if proc.poll() is not None:
                        logger.error("wpa_cli process died")
                        break
                    continue

                line = proc.stdout.readline()
                if not line:
                    break

                line = line.strip()
                if not line or line == ">" or line == "> ":
                    continue
                if line.startswith("> "):
                    line = line[2:]
                elif line.startswith(">"):
                    line = line[1:]
                line = line.strip()
                if not line:
                    continue

                # Log all events
                if "AP-STA" in line or "P2P" in line or "WPS" in line or "CTRL" in line:
                    logger.info("GO event: %s", line)

                # Handle AP-STA-CONNECTED
                match = _AP_STA_CONNECTED_PATTERN.search(line)
                if match:
                    peer_mac = match.group(1)
                    self._handle_sta_connected(peer_mac)
                    continue

                # Handle AP-STA-DISCONNECTED
                match = _AP_STA_DISCONNECTED_PATTERN.search(line)
                if match:
                    self._handle_sta_disconnected()
                    continue

                # Handle group removed
                match = _P2P_GROUP_REMOVED_PATTERN.search(line)
                if match:
                    logger.info("P2P group removed")
                    break

        except Exception as e:
            if self._running:
                logger.error("Event monitor error: %s", e)
                GLib.idle_add(self.emit, "connection-error", str(e))
        finally:
            try:
                proc.stdin.write("QUIT\n")
                proc.stdin.flush()
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            logger.info("Event monitor thread exiting")

    def _handle_sta_connected(self, peer_mac: str) -> None:
        """Handle a source device connecting via WPS."""
        logger.info("Source connected: %s", peer_mac)

        # Set up DHCP on the group interface
        our_ip = self._setup_dhcp()

        # Determine peer IP (will be assigned by our DHCP server)
        peer_ip = "192.168.49.10"  # First DHCP lease

        connection = IncomingConnection(
            peer_address=peer_mac,
            peer_ip=peer_ip,
            peer_name="Miracast Source",
            group_interface=self._group_interface,
            our_ip=our_ip,
            connected_at=datetime.now(),
            go_role=True,
        )

        with self._lock:
            self._active_connection = connection

        GLib.idle_add(self.emit, "connection-received", connection)

    def _handle_sta_disconnected(self) -> None:
        """Handle source disconnection."""
        with self._lock:
            was_connected = self._active_connection is not None
            self._active_connection = None

        if was_connected:
            logger.info("Source disconnected")
            GLib.idle_add(self.emit, "connection-lost")
            # Re-arm WPS for next connection
            self.rearm_wps_pin()

    def _setup_dhcp(self) -> str:
        """Set up IP addressing on the group interface.

        Assigns a static IP to our interface and starts dnsmasq for DHCP.
        Returns our IP address.
        """
        our_ip = "192.168.49.1"
        iface = self._group_interface

        try:
            # Assign static IP
            subprocess.run(
                ["sudo", "ip", "addr", "flush", "dev", iface],
                capture_output=True, timeout=5,
            )
            subprocess.run(
                ["sudo", "ip", "addr", "add", f"{our_ip}/24", "dev", iface],
                capture_output=True, timeout=5,
            )
            subprocess.run(
                ["sudo", "ip", "link", "set", iface, "up"],
                capture_output=True, timeout=5,
            )

            # Start dnsmasq for DHCP
            subprocess.Popen(
                [
                    "sudo", "dnsmasq",
                    f"--interface={iface}",
                    "--bind-interfaces",
                    "--dhcp-range=192.168.49.10,192.168.49.50,255.255.255.0,1h",
                    "--no-daemon",
                    "--log-facility=-",
                    f"--except-interface=lo",
                    "--no-resolv",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("DHCP server started on %s (%s/24)", iface, our_ip)
        except (OSError, subprocess.TimeoutExpired) as e:
            logger.error("Failed to set up DHCP: %s", e)

        return our_ip

    def _drain_banner(self, proc: subprocess.Popen) -> None:
        """Read and discard the wpa_cli banner lines."""
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            ready, _, _ = select.select([proc.stdout], [], [], 0.3)
            if ready:
                line = proc.stdout.readline()
                if not line:
                    break
                stripped = line.strip()
                if "Interactive mode" in stripped or stripped == ">":
                    break
            else:
                break

    def _drain_output(self, proc: subprocess.Popen, timeout: float) -> None:
        """Read and discard output for a given timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready, _, _ = select.select([proc.stdout], [], [], 0.2)
            if ready:
                proc.stdout.readline()
            else:
                break
