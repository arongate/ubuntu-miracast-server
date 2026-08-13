"""WFD Sink Advertiser for Ubuntu Miracast Server.

Manages Wi-Fi Display advertising via wpa_supplicant, setting WFD subelements
to advertise as a Primary Sink and entering P2P listen state for discoverability.
"""

import logging
import threading

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib, GObject

from miracast_server.utils import _find_p2p_interface, _run_wpa_cli

logger = logging.getLogger(__name__)

# WFD Device Information Sub-element (ID=0x00):
# Bits 0-1: Device type (01 = Primary Sink)
# Bit 4: Session available (1)
# Bit 6: WSD supported (1)
# Bit 7: Preferred connectivity = P2P (0 = P2P preferred)
# Format: device_info(2 bytes) + control_port(2 bytes) + max_throughput(2 bytes)
_WFD_DEVICE_TYPE_PRIMARY_SINK = 0x01
_WFD_SESSION_AVAILABLE = 0x10
_WFD_WSD_SUPPORTED = 0x40
# Bit 7 = 0 means P2P preferred (the bit is 0 when P2P is preferred per WFD spec)
_WFD_MAX_THROUGHPUT = 0x012C  # 300 Mbps


def _encode_wfd_device_info_subelement(rtsp_port: int) -> str:
    """Encode WFD Device Information sub-element (ID=0x00) for a Primary Sink.

    The sub-element format for wfd_subelem_set 0:
      Length(4 hex) + DeviceInfo(4 hex) + ControlPort(4 hex) + MaxThroughput(4 hex)

    DeviceInfo bits:
      - Bits 0-1: 01 (Primary Sink)
      - Bit 4: 1 (Session available)
      - Bit 6: 1 (WSD supported)
      - Bit 7: 0 (P2P preferred connectivity)

    Args:
        rtsp_port: The RTSP control port (1024-65535).

    Returns:
        Hex string for wfd_subelem_set 0 command.
    """
    device_info = _WFD_DEVICE_TYPE_PRIMARY_SINK | _WFD_SESSION_AVAILABLE | _WFD_WSD_SUPPORTED
    # Sub-element payload: 6 bytes (DeviceInfo 2 + Port 2 + Throughput 2)
    subelement = f"0006{device_info:04X}{rtsp_port:04X}{_WFD_MAX_THROUGHPUT:04X}"
    return subelement


def _encode_wfd_associated_bssid_subelement() -> str:
    """Encode WFD Associated BSSID sub-element (ID=0x01).

    All zeros indicates no associated infrastructure BSSID.
    Format: Length(4 hex) + BSSID(12 hex = 6 bytes)
    """
    return "0006000000000000"


def _encode_wfd_coupled_sink_subelement() -> str:
    """Encode WFD Coupled Sink Information sub-element (ID=0x07).

    Status byte = 0x00 (not coupled).
    Format: Length(4 hex) + CoupledSinkStatus(2 hex)
    """
    return "000100"


class MiracastAdvertiser(GObject.Object):
    """Manages WFD sink advertising via wpa_supplicant.

    Emits GObject signals for state changes:
      - advertising-started: Advertising is active and discoverable.
      - advertising-stopped: Advertising has been stopped.
      - advertising-error(str): An error occurred during advertising.

    Thread safety: All signal emissions use GLib.idle_add for main-thread dispatch.
    """

    __gsignals__ = {
        "advertising-started": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "advertising-stopped": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "advertising-error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(
        self,
        device_name: str = "Ubuntu Miracast Server",
        rtsp_port: int = 7236,
        p2p_interface: str | None = None,
    ):
        """Initialize the advertiser.

        Args:
            device_name: The device name to advertise.
            rtsp_port: RTSP control port to advertise in WFD subelements.
            p2p_interface: Override P2P interface (auto-detected if None).
        """
        super().__init__()
        self._device_name = device_name
        self._rtsp_port = rtsp_port
        self._p2p_interface = p2p_interface
        self._wifi_interface: str | None = None
        self._advertising = False
        self._lock = threading.Lock()

    @property
    def is_advertising(self) -> bool:
        """Whether the advertiser is currently active."""
        return self._advertising

    @property
    def p2p_interface(self) -> str | None:
        """The P2P interface being used."""
        return self._p2p_interface

    def start_advertising(self) -> None:
        """Start WFD sink advertising.

        Performs the following steps:
          1. Find/validate P2P interface
          2. Enable wifi_display on the interface
          3. Set WFD subelements (Primary Sink, RTSP port, session available)
          4. Set the device name
          5. Enter P2P listen state

        Idempotent: does nothing if already advertising.
        Emits advertising-started on success, advertising-error on failure.
        """
        with self._lock:
            if self._advertising:
                logger.debug("start_advertising called but already advertising — ignoring")
                return

        try:
            # Step 1: Find P2P interface
            if not self._p2p_interface:
                p2p_iface, wifi_iface = _find_p2p_interface()
                self._p2p_interface = p2p_iface
                self._wifi_interface = wifi_iface
            else:
                # Validate user-specified interface by attempting a status query
                try:
                    _run_wpa_cli(self._p2p_interface, "status")
                except RuntimeError as e:
                    raise RuntimeError(
                        f"Specified P2P interface '{self._p2p_interface}' is not valid: {e}"
                    ) from e

            iface = self._p2p_interface

            # Step 2: Enable Wi-Fi Display
            result = _run_wpa_cli(iface, "set", "wifi_display", "1")
            if "OK" not in result and "FAIL" in result:
                raise RuntimeError(f"Failed to enable wifi_display: {result}")
            logger.debug("wifi_display enabled on %s", iface)

            # Step 3: Set WFD sub-elements
            # Device Information (ID=0)
            subelement = _encode_wfd_device_info_subelement(self._rtsp_port)
            result = _run_wpa_cli(iface, "wfd_subelem_set", "0", subelement)
            if "OK" not in result and "FAIL" in result:
                raise RuntimeError(f"Failed to set WFD subelement 0: {result}")
            logger.debug("WFD Device Info subelement set: %s", subelement)

            # Associated BSSID (ID=1)
            bssid_subelem = _encode_wfd_associated_bssid_subelement()
            result = _run_wpa_cli(iface, "wfd_subelem_set", "1", bssid_subelem)
            if "OK" not in result and "FAIL" in result:
                logger.warning("Failed to set WFD Associated BSSID subelement: %s", result)
            else:
                logger.debug("WFD Associated BSSID subelement set: %s", bssid_subelem)

            # Coupled Sink Information (ID=7)
            coupled_subelem = _encode_wfd_coupled_sink_subelement()
            result = _run_wpa_cli(iface, "wfd_subelem_set", "7", coupled_subelem)
            if "OK" not in result and "FAIL" in result:
                logger.warning("Failed to set WFD Coupled Sink subelement: %s", result)
            else:
                logger.debug("WFD Coupled Sink subelement set: %s", coupled_subelem)

            # Step 4: Set device name
            result = _run_wpa_cli(iface, "set", "device_name", self._device_name, skip_last_validation=True)
            if "OK" not in result and "FAIL" in result:
                raise RuntimeError(f"Failed to set device_name: {result}")
            logger.debug("Device name set to: %s", self._device_name)

            # Step 5: Enter P2P listen state
            result = _run_wpa_cli(iface, "p2p_listen")
            if "OK" not in result and "FAIL" in result:
                raise RuntimeError(f"Failed to enter P2P listen state: {result}")
            logger.info(
                "Advertising as '%s' on %s (RTSP port %d)",
                self._device_name,
                iface,
                self._rtsp_port,
            )

            with self._lock:
                self._advertising = True

            GLib.idle_add(self.emit, "advertising-started")

        except (RuntimeError, ValueError) as e:
            error_msg = f"Failed to start advertising: {e}"
            logger.error(error_msg)
            GLib.idle_add(self.emit, "advertising-error", error_msg)

    def stop_advertising(self) -> None:
        """Stop WFD sink advertising.

        Stops P2P find/listen and emits advertising-stopped.
        Idempotent: does nothing if not currently advertising.
        """
        with self._lock:
            if not self._advertising:
                logger.debug("stop_advertising called but not advertising — ignoring")
                return
            self._advertising = False

        if self._p2p_interface:
            try:
                _run_wpa_cli(self._p2p_interface, "p2p_stop_find")
                logger.info("Stopped P2P advertising on %s", self._p2p_interface)
            except (RuntimeError, ValueError) as e:
                logger.warning("Error stopping P2P find: %s", e)

        GLib.idle_add(self.emit, "advertising-stopped")

    def update_device_name(self, name: str) -> None:
        """Update the advertised device name.

        If currently advertising, the name is updated on the interface immediately.

        Args:
            name: New device name to advertise.
        """
        self._device_name = name
        if self._advertising and self._p2p_interface:
            try:
                _run_wpa_cli(self._p2p_interface, "set", "device_name", name, skip_last_validation=True)
                logger.debug("Updated device name to: %s", name)
            except (RuntimeError, ValueError) as e:
                logger.warning("Failed to update device name: %s", e)

    def update_rtsp_port(self, port: int) -> None:
        """Update the RTSP port in WFD subelements.

        If currently advertising, the subelement is re-set on the interface.

        Args:
            port: New RTSP port (1024-65535).
        """
        self._rtsp_port = port
        if self._advertising and self._p2p_interface:
            try:
                subelement = _encode_wfd_device_info_subelement(port)
                _run_wpa_cli(self._p2p_interface, "wfd_subelem_set", "0", subelement)
                logger.debug("Updated WFD subelement with port %d", port)
            except (RuntimeError, ValueError) as e:
                logger.warning("Failed to update WFD subelement: %s", e)
