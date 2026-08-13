"""Wi-Fi Direct Connection Handler for Ubuntu Miracast Server.

Monitors wpa_supplicant events for incoming P2P connections, handles GO
negotiation, and manages the lifecycle of a single active connection.
"""

import logging
import re
import subprocess
import threading
import time
from datetime import datetime

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib, GObject

from miracast_server.models import IncomingConnection
from miracast_server.utils import _run_wpa_cli, _validate_wpa_param

logger = logging.getLogger(__name__)

# Event patterns from wpa_supplicant
_P2P_GO_NEG_REQUEST_PATTERN = re.compile(
    r"P2P-GO-NEG-REQUEST\s+([0-9a-fA-F:]{17})"
)
_P2P_GROUP_STARTED_PATTERN = re.compile(
    r"P2P-GROUP-STARTED\s+(\S+)\s+(GO|client)"
)
_P2P_GROUP_REMOVED_PATTERN = re.compile(
    r"P2P-GROUP-REMOVED\s+(\S+)"
)
_P2P_PROV_DISC_PBC_REQ_PATTERN = re.compile(
    r"P2P-PROV-DISC-PBC-REQ\s+([0-9a-fA-F:]{17})"
)
# PIN-based provision discovery: source asks us to show a PIN
_P2P_PROV_DISC_SHOW_PIN_PATTERN = re.compile(
    r"P2P-PROV-DISC-SHOW-PIN\s+([0-9a-fA-F:]{17})\s+(\d+)"
)
# PIN-based provision discovery: source will show PIN, we enter it (not used for sink)
_P2P_PROV_DISC_ENTER_PIN_PATTERN = re.compile(
    r"P2P-PROV-DISC-ENTER-PIN\s+([0-9a-fA-F:]{17})"
)
# GO negotiation success (may include PIN)
_P2P_GO_NEG_SUCCESS_PATTERN = re.compile(
    r"P2P-GO-NEG-SUCCESS"
)
# Group formation success - group is being created
_P2P_GROUP_FORMATION_SUCCESS_PATTERN = re.compile(
    r"P2P-GROUP-FORMATION-SUCCESS"
)

# Default connection timeout in seconds (60s to allow time for PIN entry)
_CONNECTION_TIMEOUT = 60


class ConnectionHandler(GObject.Object):
    """Handles incoming Wi-Fi Direct P2P connections.

    Monitors wpa_supplicant events for P2P negotiation requests, manages
    connection acceptance, and maintains a single active connection.

    GObject Signals:
      - connection-received(object): A new connection has been established.
        Payload is an IncomingConnection instance.
      - connection-lost: The active connection was lost or removed.
      - connection-error(str): An error occurred during connection handling.

    Thread safety: All signal emissions use GLib.idle_add for main-thread dispatch.
    """

    __gsignals__ = {
        "connection-received": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "connection-lost": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "connection-error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "pin-display": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),  # (pin, peer_addr)
    }

    def __init__(
        self,
        p2p_interface: str,
        go_intent: int = 15,
        auto_accept: bool = True,
        connection_timeout: int = _CONNECTION_TIMEOUT,
    ):
        """Initialize the connection handler.

        Args:
            p2p_interface: The P2P device interface name.
            go_intent: GO intent value (0-15) for negotiation.
            auto_accept: Whether to auto-accept incoming connection requests.
            connection_timeout: Seconds to wait for group formation after p2p_connect.
        """
        super().__init__()
        self._p2p_interface = p2p_interface
        self._go_intent = go_intent
        self._auto_accept = auto_accept
        self._connection_timeout = connection_timeout

        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._active_connection: IncomingConnection | None = None
        self._pending_connect_time: float | None = None
        self._pending_peer: str | None = None  # Peer address of pending connection

    @property
    def is_listening(self) -> bool:
        """Whether the handler is currently listening for connections."""
        return self._running

    @property
    def active_connection(self) -> IncomingConnection | None:
        """The currently active connection, or None."""
        with self._lock:
            return self._active_connection

    def start_listening(self) -> None:
        """Start listening for incoming P2P connections.

        Spawns a daemon thread that monitors wpa_cli events for connection
        requests and group formation.
        """
        if self._running:
            logger.debug("start_listening called but already listening — ignoring")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._event_monitor_loop,
            name="p2p-event-monitor",
            daemon=True,
        )
        self._thread.start()
        logger.info("Connection handler started listening on %s", self._p2p_interface)

    def stop_listening(self) -> None:
        """Stop listening for connections.

        Sets the running flag and joins the monitor thread within 5 seconds.
        """
        if not self._running:
            return

        self._running = False

        if self._thread:
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("Event monitor thread did not stop within 5 seconds")
            self._thread = None

        logger.info("Connection handler stopped listening")

    def disconnect_peer(self) -> None:
        """Disconnect the currently connected peer.

        Issues p2p_group_remove and clears the active connection state.
        """
        with self._lock:
            connection = self._active_connection
            self._active_connection = None

        if connection and connection.group_interface:
            try:
                _run_wpa_cli(
                    self._p2p_interface,
                    "p2p_group_remove",
                    connection.group_interface,
                )
                logger.info("Disconnected peer on %s", connection.group_interface)
            except (RuntimeError, ValueError) as e:
                logger.warning("Error removing P2P group: %s", e)

    def _event_monitor_loop(self) -> None:
        """Main event monitoring loop running in a daemon thread.

        Spawns wpa_cli in interactive mode and sends ATTACH to receive
        unsolicited events from wpa_supplicant.
        """
        logger.debug("Event monitor thread started")

        try:
            proc = subprocess.Popen(
                ["sudo", "wpa_cli", "-i", self._p2p_interface],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as e:
            error_msg = f"Failed to start wpa_cli event monitor: {e}"
            logger.error(error_msg)
            GLib.idle_add(self.emit, "connection-error", error_msg)
            return

        try:
            # Read the initial prompt/banner
            import select
            ready, _, _ = select.select([proc.stdout], [], [], 3.0)
            if ready:
                banner = proc.stdout.readline()
                logger.debug("wpa_cli banner: %s", banner.strip())

            # Send ATTACH to register for unsolicited events
            proc.stdin.write("ATTACH\n")
            proc.stdin.flush()
            # Read ATTACH response
            ready, _, _ = select.select([proc.stdout], [], [], 3.0)
            if ready:
                attach_resp = proc.stdout.readline()
                logger.debug("wpa_cli ATTACH response: %s", attach_resp.strip())
                if "OK" not in attach_resp and ">" not in attach_resp:
                    logger.warning("ATTACH may have failed: %s", attach_resp.strip())

            logger.info("Event monitor attached to %s", self._p2p_interface)

            while self._running:
                # Check for connection timeout
                self._check_connection_timeout()

                # Read events
                line = self._read_line_with_timeout(proc, timeout=1.0)
                if line is None:
                    continue

                line = line.strip()
                if not line or line == ">" or line.startswith(">"):
                    # Strip interactive prompt prefix
                    if line.startswith(">"):
                        line = line[1:].strip()
                    if not line:
                        continue

                # Process P2P events
                self._process_event(line)

        except Exception as e:
            if self._running:
                error_msg = f"Event monitor error: {e}"
                logger.error(error_msg)
                GLib.idle_add(self.emit, "connection-error", error_msg)
        finally:
            try:
                if proc.stdin:
                    proc.stdin.write("QUIT\n")
                    proc.stdin.flush()
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        logger.debug("Event monitor thread exiting")

    def _read_line_with_timeout(
        self, proc: subprocess.Popen, timeout: float
    ) -> str | None:
        """Read a line from the wpa_cli process with timeout.

        Uses a non-blocking approach with select-like polling.
        """
        import select

        if proc.stdout is None:
            return None

        try:
            ready, _, _ = select.select([proc.stdout], [], [], timeout)
            if ready:
                line = proc.stdout.readline()
                if not line:
                    # Process has exited
                    if self._running:
                        raise RuntimeError("wpa_cli process exited unexpectedly")
                    return None
                return line
        except (OSError, ValueError):
            if self._running:
                raise
        return None

    def _process_event(self, line: str) -> None:
        """Process a single wpa_supplicant event line."""
        # Log all P2P events for debugging
        if "P2P" in line or "WPS" in line or "CTRL" in line:
            logger.debug("wpa_event: %s", line.strip())

        # P2P-GO-NEG-REQUEST: incoming connection negotiation request
        match = _P2P_GO_NEG_REQUEST_PATTERN.search(line)
        if match:
            peer_addr = match.group(1)
            self._handle_go_neg_request(peer_addr)
            return

        # P2P-PROV-DISC-PBC-REQ: PBC provisioning discovery request
        match = _P2P_PROV_DISC_PBC_REQ_PATTERN.search(line)
        if match:
            peer_addr = match.group(1)
            self._handle_go_neg_request(peer_addr)
            return

        # P2P-PROV-DISC-SHOW-PIN: source requests us to display a PIN
        match = _P2P_PROV_DISC_SHOW_PIN_PATTERN.search(line)
        if match:
            peer_addr = match.group(1)
            pin = match.group(2)
            self._handle_show_pin(peer_addr, pin)
            return

        # P2P-PROV-DISC-ENTER-PIN: source will show a PIN for us to enter
        match = _P2P_PROV_DISC_ENTER_PIN_PATTERN.search(line)
        if match:
            peer_addr = match.group(1)
            self._handle_enter_pin_request(peer_addr)
            return

        # P2P-GROUP-STARTED: group has been formed
        match = _P2P_GROUP_STARTED_PATTERN.search(line)
        if match:
            group_iface = match.group(1)
            role = match.group(2)
            self._handle_group_started(group_iface, role, line)
            return

        # P2P-GROUP-FORMATION-SUCCESS: group is being created, poll for interface
        match = _P2P_GROUP_FORMATION_SUCCESS_PATTERN.search(line)
        if match:
            logger.info("P2P group formation successful — polling for group interface")
            self._poll_for_group_interface()
            return

        # P2P-GO-NEG-SUCCESS: GO negotiation completed
        match = _P2P_GO_NEG_SUCCESS_PATTERN.search(line)
        if match:
            logger.info("GO negotiation successful: %s", line.strip())
            return

        # P2P-GROUP-REMOVED: group has been removed
        match = _P2P_GROUP_REMOVED_PATTERN.search(line)
        if match:
            self._handle_group_removed()
            return

    def _handle_go_neg_request(self, peer_addr: str) -> None:
        """Handle an incoming GO negotiation request.

        For a sink, we authorize the connection with 'p2p_connect <addr> pbc auth'
        which means we accept PBC-based GO negotiation initiated by the source.
        """
        with self._lock:
            if self._active_connection is not None:
                logger.info(
                    "Ignoring GO-NEG-REQUEST from %s — connection already active",
                    peer_addr,
                )
                return

        if not self._auto_accept:
            logger.info(
                "GO-NEG-REQUEST from %s — auto-accept disabled, ignoring",
                peer_addr,
            )
            return

        logger.info("Accepting P2P connection from %s (PBC)", peer_addr)

        try:
            # Use 'auth' — authorize the peer to connect via PBC.
            # The source initiates GO Negotiation, we just accept it.
            _run_wpa_cli(
                self._p2p_interface,
                "p2p_connect",
                peer_addr,
                "pbc",
                "auth",
            )
            self._pending_connect_time = time.monotonic()
            logger.debug("p2p_connect (pbc auth) issued for %s", peer_addr)
        except (RuntimeError, ValueError) as e:
            error_msg = f"Failed to accept connection from {peer_addr}: {e}"
            logger.error(error_msg)
            GLib.idle_add(self.emit, "connection-error", error_msg)

    def _handle_show_pin(self, peer_addr: str, pin: str) -> None:
        """Handle P2P-PROV-DISC-SHOW-PIN event.

        This means: wpa_supplicant generated a PIN for us to display.
        The user on the source device must enter this PIN to confirm the connection.

        Flow:
        1. Display the PIN on our UI
        2. Authorize the connection with 'p2p_connect <addr> <pin> display auth'
        3. Wait for the source to complete GO Negotiation using this PIN
        """
        with self._lock:
            if self._active_connection is not None:
                logger.info("Ignoring SHOW-PIN from %s — connection already active", peer_addr)
                return
            # Ignore duplicate PROV-DISC events while we're already handling one
            if self._pending_peer is not None:
                logger.info("Ignoring duplicate SHOW-PIN from %s — already pending", peer_addr)
                return

        if not self._auto_accept:
            logger.info("SHOW-PIN from %s — auto-accept disabled, ignoring", peer_addr)
            return

        logger.info("PIN to display: %s (peer: %s)", pin, peer_addr)

        # Emit signal IMMEDIATELY to show PIN on the UI
        GLib.idle_add(self.emit, "pin-display", pin, peer_addr)

        try:
            # 'display auth' = I'm displaying this PIN, authorize the peer to connect
            _run_wpa_cli(
                self._p2p_interface,
                "p2p_connect",
                peer_addr,
                pin,
                "display",
                "auth",
            )
            with self._lock:
                self._pending_peer = peer_addr
            self._pending_connect_time = time.monotonic()
            logger.info("p2p_connect (pin=%s display auth) issued for %s", pin, peer_addr)
        except (RuntimeError, ValueError) as e:
            error_msg = f"Failed to authorize PIN connection from {peer_addr}: {e}"
            logger.error(error_msg)
            GLib.idle_add(self.emit, "connection-error", error_msg)

    def _handle_enter_pin_request(self, peer_addr: str) -> None:
        """Handle P2P-PROV-DISC-ENTER-PIN event.

        This means: the source is displaying a PIN and we need to enter it.
        For a sink/display device, this is unusual. We respond by generating
        our own PIN and using 'display' method so the source enters our PIN instead.
        """
        with self._lock:
            if self._active_connection is not None:
                logger.info("Ignoring ENTER-PIN from %s — connection already active", peer_addr)
                return

        if not self._auto_accept:
            return

        logger.info("ENTER-PIN request from %s — responding with our own PIN via display", peer_addr)

        try:
            # Generate our own PIN by using 'pin' method which returns the PIN
            result = _run_wpa_cli(
                self._p2p_interface,
                "p2p_connect",
                peer_addr,
                "pin",
                "display",
                "auth",
            )
            # The result contains the generated PIN
            pin = result.strip()
            if pin and pin.isdigit():
                logger.info("Generated PIN to display: %s (peer: %s)", pin, peer_addr)
                GLib.idle_add(self.emit, "pin-display", pin, peer_addr)
                self._pending_connect_time = time.monotonic()
            else:
                logger.warning("Unexpected p2p_connect pin response: %s", result)
        except (RuntimeError, ValueError) as e:
            error_msg = f"Failed to handle ENTER-PIN from {peer_addr}: {e}"
            logger.error(error_msg)
            GLib.idle_add(self.emit, "connection-error", error_msg)

    def _poll_for_group_interface(self) -> None:
        """Poll for P2P group interface after GROUP-FORMATION-SUCCESS.

        The P2P-GROUP-STARTED event may not arrive on p2p-dev-wlo1.
        We poll network interfaces to detect the newly created p2p group interface.
        """
        # Poll for up to 30 seconds (the group interface can take time to appear)
        for attempt in range(30):
            time.sleep(1)
            if not self._running:
                return
            # Already handled by a P2P-GROUP-STARTED event
            with self._lock:
                if self._active_connection is not None:
                    return

            # Use 'ip link' to find p2p group interfaces
            try:
                result = subprocess.run(
                    ["ip", "link", "show"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    for line in result.stdout.split("\n"):
                        # Look for p2p- prefixed interfaces
                        # Format: "X: p2p-wlo1-0: <BROADCAST,..."
                        if ": p2p-" in line:
                            parts = line.split(": ")
                            if len(parts) >= 2:
                                iface_name = parts[1].rstrip(":")
                                # Remove @ suffix if present (e.g., "p2p-wlo1-0@wlo1")
                                iface_name = iface_name.split("@")[0]
                                logger.info(
                                    "Found P2P group interface: %s (poll attempt %d)",
                                    iface_name, attempt + 1,
                                )
                                # Determine role
                                role = "client"
                                try:
                                    status = _run_wpa_cli(iface_name, "status")
                                    if "mode=P2P GO" in status:
                                        role = "GO"
                                except (RuntimeError, ValueError):
                                    pass

                                self._handle_group_started(iface_name, role, "")
                                return
            except (subprocess.TimeoutExpired, OSError) as e:
                logger.debug("ip link poll error: %s", e)

            # Also check if the event appeared in the wpa_cli output while we were polling
            # (it might have been read and processed by _process_event in the main loop)
            with self._lock:
                if self._active_connection is not None:
                    return

        logger.warning("Could not find P2P group interface after 30 seconds of polling")

    def _handle_group_started(
        self, group_iface: str, role: str, event_line: str
    ) -> None:
        """Handle P2P-GROUP-STARTED event.

        Extracts connection details, handles DHCP, and emits connection-received.
        """
        self._pending_connect_time = None
        with self._lock:
            self._pending_peer = None
        logger.info("P2P group started: interface=%s role=%s", group_iface, role)

        try:
            # FR-CH04: Handle DHCP after group formation
            is_go = role.lower() == "go"
            self._handle_dhcp(group_iface, is_go)

            # Query group status to get IP addresses and peer info
            peer_ip, our_ip, peer_addr, peer_name = self._query_group_info(group_iface)

            connection = IncomingConnection(
                peer_address=peer_addr,
                peer_ip=peer_ip,
                peer_name=peer_name,
                group_interface=group_iface,
                our_ip=our_ip,
                connected_at=datetime.now(),
                go_role=is_go,
            )

            with self._lock:
                self._active_connection = connection

            logger.info(
                "Connection established: peer=%s (%s) on %s",
                peer_name,
                peer_ip,
                group_iface,
            )
            GLib.idle_add(self.emit, "connection-received", connection)

        except Exception as e:
            error_msg = f"Failed to process group started: {e}"
            logger.error(error_msg)
            GLib.idle_add(self.emit, "connection-error", error_msg)

    def _handle_group_removed(self) -> None:
        """Handle P2P-GROUP-REMOVED event."""
        with self._lock:
            was_connected = self._active_connection is not None
            self._active_connection = None

        if was_connected:
            logger.info("P2P group removed — connection lost")
            GLib.idle_add(self.emit, "connection-lost")

    def _handle_dhcp(self, group_iface: str, is_go: bool) -> None:
        """Handle DHCP IP address assignment after P2P group formation (FR-CH04).

        If we are the P2P Client: run dhclient to obtain an IP address.
        If we are the P2P GO: start dnsmasq to assign IPs to the connected peer.

        Args:
            group_iface: The P2P group interface name.
            is_go: Whether we are the Group Owner.
        """
        if is_go:
            # We are GO — assign ourselves an IP and start DHCP server for peer
            try:
                # Assign ourselves a static IP on the GO interface
                subprocess.run(
                    ["sudo", "ip", "addr", "add", "192.168.49.1/24", "dev", group_iface],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                subprocess.run(
                    ["sudo", "ip", "link", "set", group_iface, "up"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                # Start dnsmasq as DHCP server on the interface
                subprocess.Popen(
                    [
                        "sudo", "dnsmasq",
                        f"--interface={group_iface}",
                        "--bind-interfaces",
                        "--dhcp-range=192.168.49.50,192.168.49.150,255.255.255.0,12h",
                        "--no-daemon",
                        "--log-facility=-",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logger.info("Started DHCP server (dnsmasq) on %s as GO", group_iface)
            except (OSError, subprocess.TimeoutExpired) as e:
                logger.warning("Failed to start DHCP server: %s", e)
        else:
            # We are Client — request IP via dhclient
            try:
                result = subprocess.run(
                    ["sudo", "dhclient", "-1", group_iface],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if result.returncode == 0:
                    logger.info("DHCP client obtained IP on %s", group_iface)
                else:
                    # Fallback: try dhcpcd
                    result = subprocess.run(
                        ["sudo", "dhcpcd", group_iface],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    if result.returncode == 0:
                        logger.info("dhcpcd obtained IP on %s", group_iface)
                    else:
                        logger.warning(
                            "DHCP failed on %s: %s",
                            group_iface,
                            result.stderr.strip(),
                        )
            except (OSError, subprocess.TimeoutExpired) as e:
                logger.warning("DHCP client error on %s: %s", group_iface, e)

    def _query_group_info(
        self, group_iface: str
    ) -> tuple[str, str, str, str]:
        """Query the P2P group interface for connection details.

        Attempts to determine peer IP, our IP, peer MAC, and peer name
        by querying wpa_cli status and interface info.

        Args:
            group_iface: The P2P group interface name.

        Returns:
            Tuple of (peer_ip, our_ip, peer_address, peer_name).
        """
        peer_ip = "0.0.0.0"
        our_ip = "0.0.0.0"
        peer_addr = "00:00:00:00:00:00"
        peer_name = "Unknown"

        # Query status on the group interface
        try:
            status_output = _run_wpa_cli(group_iface, "status")
            for line in status_output.split("\n"):
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    if key == "ip_address":
                        our_ip = value
                    elif key == "p2p_device_address":
                        peer_addr = value
        except (RuntimeError, ValueError) as e:
            logger.warning("Failed to query group status: %s", e)

        # Try to get peer IP via DHCP or ARP
        try:
            our_ip_from_ifconfig = self._get_interface_ip(group_iface)
            if our_ip_from_ifconfig:
                our_ip = our_ip_from_ifconfig
        except Exception as e:
            logger.debug("Failed to get interface IP: %s", e)

        # Get peer IP — if we are GO, check dhcp leases; if client, peer is gateway
        try:
            peer_ip = self._get_peer_ip(group_iface, our_ip)
        except Exception as e:
            logger.debug("Failed to determine peer IP: %s", e)

        # Try to get peer name from p2p_peer query
        try:
            if peer_addr != "00:00:00:00:00:00":
                peer_info = _run_wpa_cli(self._p2p_interface, "p2p_peer", peer_addr)
                for line in peer_info.split("\n"):
                    if line.startswith("device_name="):
                        peer_name = line.split("=", 1)[1].strip()
                        break
        except (RuntimeError, ValueError) as e:
            logger.debug("Failed to query peer info: %s", e)

        return peer_ip, our_ip, peer_addr, peer_name

    def _get_interface_ip(self, iface: str) -> str | None:
        """Get the IP address assigned to a network interface."""
        try:
            result = subprocess.run(
                ["ip", "addr", "show", iface],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    line = line.strip()
                    if line.startswith("inet "):
                        # Format: inet 192.168.x.x/24 ...
                        ip_cidr = line.split()[1]
                        return ip_cidr.split("/")[0]
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.debug("ip addr show failed: %s", e)
        return None

    def _get_peer_ip(self, group_iface: str, our_ip: str) -> str:
        """Determine the peer's IP address.

        If we're the GO, check ARP table. Otherwise, the gateway is the peer.
        """
        # Check ARP table for entries on the group interface
        try:
            result = subprocess.run(
                ["ip", "neigh", "show", "dev", group_iface],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().split("\n"):
                    parts = line.split()
                    if parts and parts[0] != our_ip:
                        return parts[0]
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.debug("ARP lookup failed: %s", e)

        # Fallback: try the gateway route
        try:
            result = subprocess.run(
                ["ip", "route", "show", "dev", group_iface],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if "via" in line:
                        parts = line.split()
                        via_idx = parts.index("via")
                        if via_idx + 1 < len(parts):
                            return parts[via_idx + 1]
        except (subprocess.TimeoutExpired, OSError, ValueError) as e:
            logger.debug("Route lookup failed: %s", e)

        return "0.0.0.0"

    def _check_connection_timeout(self) -> None:
        """Check if a pending connection has timed out."""
        if self._pending_connect_time is None:
            return

        elapsed = time.monotonic() - self._pending_connect_time
        if elapsed >= self._connection_timeout:
            self._pending_connect_time = None
            with self._lock:
                self._pending_peer = None
            error_msg = (
                f"Connection timeout: no P2P group formed within "
                f"{self._connection_timeout} seconds"
            )
            logger.error(error_msg)

            # Cancel any pending P2P operation
            try:
                _run_wpa_cli(self._p2p_interface, "p2p_cancel")
            except (RuntimeError, ValueError):
                pass

            # Re-enter listen state so we're discoverable again
            try:
                _run_wpa_cli(self._p2p_interface, "p2p_listen")
                logger.info("Re-entered P2P listen after connection timeout")
            except (RuntimeError, ValueError) as e:
                logger.warning("Failed to re-enter P2P listen: %s", e)

            GLib.idle_add(self.emit, "connection-error", error_msg)
