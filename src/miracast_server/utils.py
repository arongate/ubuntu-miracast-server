"""Core utility and shared helpers for the Miracast Server.

Provides validated subprocess wrappers, codec whitelisting, and RTSP
security enforcement. All security-sensitive validation is centralized here.
"""

import logging
import re
import subprocess

logger = logging.getLogger(__name__)

# Allowed characters for wpa_cli parameters: alphanumeric, colons, hyphens, underscores
_WPA_PARAM_PATTERN = re.compile(r"^[a-zA-Z0-9:\-_]+$")

# ─── Codec and RTSP Security Constants ────────────────────────────────────────

# Codec whitelist for pipeline construction (requirement 10.4)
ALLOWED_VIDEO_CODECS = frozenset({"H264"})
ALLOWED_AUDIO_CODECS = frozenset({"AAC"})

# RTSP request size limits (requirement 10.7)
RTSP_MAX_HEADER_SIZE = 8192  # 8 KB
RTSP_MAX_BODY_SIZE = 65536  # 64 KB


def validate_codec(codec: str, codec_type: str = "video") -> bool:
    """Validate a codec name against the whitelist.

    Args:
        codec: Codec name to validate (e.g. "H264", "AAC").
        codec_type: Either "video" or "audio".

    Returns:
        True if the codec is allowed, False otherwise.
    """
    if codec_type == "video":
        return codec in ALLOWED_VIDEO_CODECS
    elif codec_type == "audio":
        return codec in ALLOWED_AUDIO_CODECS
    return False


def validate_rtsp_size(header_bytes: int, body_bytes: int) -> bool:
    """Validate RTSP message sizes against security limits.

    Args:
        header_bytes: Size of the header block in bytes.
        body_bytes: Size of the body in bytes.

    Returns:
        True if within limits, False if exceeded.
    """
    return header_bytes <= RTSP_MAX_HEADER_SIZE and body_bytes <= RTSP_MAX_BODY_SIZE


def validate_port(port: int) -> bool:
    """Validate a network port number.

    Args:
        port: Port number to validate.

    Returns:
        True if port is in range 1024-65535.
    """
    return isinstance(port, int) and 1024 <= port <= 65535


def list_p2p_interfaces() -> list[dict[str, str]]:
    """List all available P2P device interfaces on the system.

    Queries both wpa_supplicant and NetworkManager to find P2P-capable interfaces.

    Returns:
        List of dicts with keys: 'interface' (P2P dev name), 'parent' (wifi iface),
        'driver', 'status' (connected/disconnected).
    """
    interfaces = []
    seen = set()

    # Method 1: Query wpa_supplicant
    try:
        result = subprocess.run(
            ["sudo", "wpa_cli", "interface"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line.startswith("p2p-dev-"):
                    if line not in seen:
                        seen.add(line)
                        parent = line.replace("p2p-dev-", "")
                        interfaces.append(_get_interface_info(line, parent))
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.debug("wpa_cli interface query failed: %s", e)

    # Method 2: Query NetworkManager for wifi-p2p devices
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                parts = line.split(":")
                if len(parts) >= 3 and parts[1] == "wifi-p2p":
                    iface_name = parts[0]
                    if iface_name not in seen:
                        seen.add(iface_name)
                        parent = iface_name.replace("p2p-dev-", "")
                        interfaces.append(_get_interface_info(iface_name, parent))
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.debug("nmcli query failed: %s", e)

    return interfaces


def _get_interface_info(iface_name: str, parent: str) -> dict[str, str]:
    """Get detailed info about a P2P interface."""
    driver = ""
    try:
        drv_result = subprocess.run(
            ["ethtool", "-i", parent],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if drv_result.returncode == 0:
            for drv_line in drv_result.stdout.split("\n"):
                if drv_line.startswith("driver:"):
                    driver = drv_line.split(":", 1)[1].strip()
                    break
    except (subprocess.TimeoutExpired, OSError):
        pass

    status = "available"
    try:
        nm_result = subprocess.run(
            ["nmcli", "-t", "-f", "DEVICE,STATE", "device", "status"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if nm_result.returncode == 0:
            for nm_line in nm_result.stdout.split("\n"):
                if nm_line.startswith(f"{parent}:"):
                    state = nm_line.split(":", 1)[1]
                    if "connected" in state:
                        status = "connected"
                    else:
                        status = "disconnected"
    except (subprocess.TimeoutExpired, OSError):
        pass

    return {
        "interface": iface_name,
        "parent": parent,
        "driver": driver,
        "status": status,
    }


def _validate_wpa_param(param: str) -> bool:
    """Validate a wpa_cli parameter against the allowlist.

    A parameter is valid if and only if every character is alphanumeric,
    a colon, a hyphen, or an underscore.

    Args:
        param: The parameter string to validate.

    Returns:
        True if the parameter is valid, False otherwise.
    """
    if not param:
        return False
    return bool(_WPA_PARAM_PATTERN.match(param))


def _find_p2p_interface() -> tuple[str | None, str | None]:
    """Find the P2P device interface name.

    Detects a P2P-capable Wi-Fi interface by looking at wpa_supplicant interfaces.

    Returns:
        Tuple of (p2p_interface, wifi_interface) or (None, None) if not found.

    Raises:
        RuntimeError: If no P2P-capable interface is detected.
    """
    try:
        result = subprocess.run(
            ["sudo", "wpa_cli", "interface"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "wpa_cli returned non-zero exit code. "
                "Ensure wpa_supplicant is running with P2P support."
            )

        lines = result.stdout.strip().split("\n")
        p2p_iface = None
        wifi_iface = None
        for line in lines:
            line = line.strip()
            if line.startswith("p2p-dev-"):
                p2p_iface = line
                wifi_iface = line.replace("p2p-dev-", "")
            elif line.startswith("wl") and not wifi_iface:
                wifi_iface = line

        if not p2p_iface:
            raise RuntimeError(
                "No P2P-capable interface detected. "
                "Ensure Wi-Fi is enabled and wpa_supplicant has P2P support."
            )

        return p2p_iface, wifi_iface
    except subprocess.TimeoutExpired as e:
        logger.error(f"Timeout finding P2P interface: {e}")
        raise RuntimeError("Timeout communicating with wpa_supplicant.") from e
    except OSError as e:
        logger.error(f"Failed to execute wpa_cli: {e}")
        raise RuntimeError(
            f"Failed to execute wpa_cli: {e}. "
            "Ensure wpa_supplicant is installed and accessible."
        ) from e


def _run_wpa_cli(interface: str, *args: str, skip_last_validation: bool = False) -> str:
    """Run a wpa_cli command with parameter validation.

    All parameters are validated against an allowlist (alphanumeric, colons,
    hyphens, and underscores only). Uses list-based subprocess calls (no shell=True).

    Args:
        interface: The wpa_supplicant interface to operate on.
        *args: Additional arguments to pass to wpa_cli.
        skip_last_validation: If True, the last argument is treated as a
            user-provided value (e.g., device_name) and is not validated
            against the strict allowlist. Still safe because subprocess
            uses list format (no shell injection).

    Returns:
        The stdout output from the wpa_cli command.

    Raises:
        ValueError: If any parameter contains disallowed characters.
        RuntimeError: If the wpa_cli command fails or times out.
    """
    # Validate interface
    if not _validate_wpa_param(interface):
        raise ValueError(
            f"Invalid interface name '{interface}': "
            "only alphanumeric characters, colons, hyphens, and underscores are allowed."
        )

    # Validate arguments
    args_to_validate = args[:-1] if (skip_last_validation and args) else args
    for arg in args_to_validate:
        if not _validate_wpa_param(arg):
            raise ValueError(
                f"Invalid wpa_cli parameter '{arg}': "
                "only alphanumeric characters, colons, hyphens, and underscores are allowed."
            )

    # Build command as a list (no shell=True)
    cmd = ["sudo", "wpa_cli", "-i", interface] + list(args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.error(
                f"wpa_cli command failed: {' '.join(cmd)}\n"
                f"stdout: {result.stdout.strip()}\n"
                f"stderr: {result.stderr.strip()}"
            )
            raise RuntimeError(
                f"wpa_cli command failed with exit code {result.returncode}: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return result.stdout.strip()
    except subprocess.TimeoutExpired as e:
        logger.error(f"wpa_cli command timed out: {' '.join(cmd)}")
        raise RuntimeError(f"wpa_cli command timed out: {' '.join(cmd)}") from e
    except OSError as e:
        logger.error(f"Failed to execute wpa_cli: {e}")
        raise RuntimeError(f"Failed to execute wpa_cli: {e}") from e
