"""WFD Sink Advertiser for Ubuntu Miracast Server.

Uses the Autonomous Group Owner approach: creates a P2P GO first, then
arms WPS PIN on the group interface. This is the proven approach used by
lazycast and 7herbert for reliable Miracast sink operation.

Architecture:
  1. Set WFD subelements (Primary Sink)
  2. Create P2P Group Owner (p2p_group_add)
  3. Monitor for group interface creation
  4. Set WFD subelements on the group interface
  5. The GO beacon makes us discoverable — no p2p_listen needed
"""

import logging
import re
import subprocess
import threading
import time

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib, GObject

from miracast_server.utils import _run_wpa_cli

logger = logging.getLogger(__name__)

# WFD Device Info: Primary Sink (01) + Session Available (10) + WSD (40) = 0x0051
_WFD_DEVICE_INFO_SUBELEMENT = "000600511C44012C"  # DevInfo=0051, Port=7236, Throughput=300
_WFD_ASSOCIATED_BSSID_SUBELEMENT = "0006000000000000"
_WFD_COUPLED_SINK_SUBELEMENT = "000700000000000000"


def _encode_wfd_device_info(rtsp_port: int) -> str:
    """Encode WFD Device Information sub-element for a Primary Sink."""
    device_info = 0x0051  # Primary Sink + Session Available + WSD
    throughput = 0x012C  # 300 Mbps
    return f"0006{device_info:04X}{rtsp_port:04X}{throughput:04X}"


class MiracastAdvertiser(GObject.Object):
    """Manages WFD sink advertising via Autonomous P2P Group Owner.

    Instead of using p2p_listen (unreliable), this creates a P2P Group Owner
    which broadcasts a beacon that source devices can discover and connect to.

    Signals:
      - advertising-started(str): GO created, payload is group interface name
      - advertising-stopped: GO removed
      - advertising-error(str): Error occurred
    """

    __gsignals__ = {
        "advertising-started": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "advertising-stopped": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "advertising-error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(
        self,
        device_name: str = "Ubuntu Miracast Server",
        rtsp_port: int = 7236,
        p2p_interface: str | None = None,
        ctrl_path: str | None = None,
    ):
        super().__init__()
        self._device_name = device_name
        self._rtsp_port = rtsp_port
        self._p2p_interface = p2p_interface
        self._ctrl_path = ctrl_path
        self._group_interface: str | None = None
        self._advertising = False
        self._lock = threading.Lock()

    @property
    def is_advertising(self) -> bool:
        return self._advertising

    @property
    def p2p_interface(self) -> str | None:
        return self._p2p_interface

    @property
    def ctrl_path(self) -> str | None:
        return self._ctrl_path

    @property
    def group_interface(self) -> str | None:
        """The P2P group interface created by p2p_group_add."""
        return self._group_interface

    def _wpa(self, *args: str, interface: str | None = None, **kwargs) -> str:
        """Run wpa_cli command on the specified or default interface."""
        iface = interface or self._p2p_interface
        return _run_wpa_cli(iface, *args, ctrl_path=self._ctrl_path, **kwargs)

    def start_advertising(self) -> None:
        """Start WFD sink advertising by creating an Autonomous P2P Group Owner.

        Flow:
          1. Find/validate interface
          2. Enable wifi_display and set WFD subelements
          3. Create P2P Group Owner (p2p_group_add persistent)
          4. Detect the created group interface
          5. Set WFD subelements on the group interface
        """
        with self._lock:
            if self._advertising:
                logger.debug("Already advertising — ignoring")
                return

        try:
            # Step 1: Resolve interface
            if not self._p2p_interface:
                from miracast_server.utils import _find_p2p_interface
                p2p_iface, _ = _find_p2p_interface()
                self._p2p_interface = p2p_iface

            iface = self._p2p_interface
            logger.info("Setting up P2P GO on %s", iface)

            # Step 2: Enable WFD and set subelements
            self._wpa("set", "wifi_display", "1")
            self._wpa("wfd_subelem_set", "0", _encode_wfd_device_info(self._rtsp_port))
            self._wpa("wfd_subelem_set", "1", _WFD_ASSOCIATED_BSSID_SUBELEMENT)
            self._wpa("wfd_subelem_set", "6", _WFD_COUPLED_SINK_SUBELEMENT)
            self._wpa("set", "device_name", self._device_name, skip_last_validation=True)
            self._wpa("set", "device_type", "7-0050F204-1")
            logger.debug("WFD subelements configured")

            # Step 3: Create Autonomous P2P Group Owner
            result = self._wpa("p2p_group_add", "persistent")
            if "FAIL" in result:
                raise RuntimeError(f"p2p_group_add failed: {result}")
            logger.info("p2p_group_add issued, waiting for group interface...")

            # Step 4: Wait for the group interface to appear
            group_iface = self._wait_for_group_interface(timeout=10)
            if not group_iface:
                raise RuntimeError("P2P group interface did not appear within 10 seconds")

            self._group_interface = group_iface
            logger.info("P2P GO created on interface: %s", group_iface)

            # Step 5: Set WFD subelements on the group interface too
            try:
                self._wpa("set", "wifi_display", "1", interface=group_iface)
                self._wpa("wfd_subelem_set", "0", _encode_wfd_device_info(self._rtsp_port), interface=group_iface)
            except RuntimeError as e:
                logger.debug("Could not set WFD on group iface (may not be needed): %s", e)

            with self._lock:
                self._advertising = True

            GLib.idle_add(self.emit, "advertising-started", group_iface)
            logger.info(
                "Advertising as '%s' via GO on %s (RTSP port %d)",
                self._device_name, group_iface, self._rtsp_port,
            )

        except (RuntimeError, ValueError) as e:
            error_msg = f"Failed to start advertising: {e}"
            logger.error(error_msg)
            GLib.idle_add(self.emit, "advertising-error", error_msg)

    def stop_advertising(self) -> None:
        """Stop advertising by removing the P2P group."""
        with self._lock:
            if not self._advertising:
                return
            self._advertising = False

        if self._group_interface:
            try:
                self._wpa("p2p_group_remove", self._group_interface)
                logger.info("Removed P2P group on %s", self._group_interface)
            except (RuntimeError, ValueError) as e:
                logger.warning("Error removing P2P group: %s", e)
            self._group_interface = None

        GLib.idle_add(self.emit, "advertising-stopped")

    def _wait_for_group_interface(self, timeout: float) -> str | None:
        """Wait for the P2P group interface to appear after p2p_group_add.

        Polls `ip link` for a p2p-* interface.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                result = subprocess.run(
                    ["ip", "link", "show"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    for line in result.stdout.split("\n"):
                        if ": p2p-" in line:
                            parts = line.split(": ")
                            if len(parts) >= 2:
                                iface_name = parts[1].split("@")[0].rstrip(":")
                                return iface_name
            except (subprocess.TimeoutExpired, OSError):
                pass
            time.sleep(0.5)
        return None
