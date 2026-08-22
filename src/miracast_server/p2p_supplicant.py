"""Dedicated wpa_supplicant instance manager for P2P operations.

Manages a separate wpa_supplicant process for a dedicated Wi-Fi adapter,
enabling simultaneous internet (on the primary adapter) and Miracast P2P
(on the dedicated adapter) without channel conflicts.
"""

import logging
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_WPA_CONF_TEMPLATE = """\
ctrl_interface={ctrl_dir}
update_config=1
device_name={device_name}
device_type=7-0050F204-1
p2p_go_intent=1
driver_param=p2p_device=1
country=FR
"""

# Default paths
_CTRL_DIR = "/tmp/miracast-wpa-p2p"
_CONF_PATH = "/tmp/miracast-wpa-p2p.conf"
_LOG_PATH = "/tmp/miracast-wpa-p2p.log"


class P2PSupplicantManager:
    """Manages a dedicated wpa_supplicant instance for P2P on a secondary Wi-Fi adapter.

    Lifecycle:
      1. Unmanage the adapter from NetworkManager
      2. Write a minimal wpa_supplicant config with P2P support
      3. Spawn a dedicated wpa_supplicant process on the adapter
      4. Provide the control socket path for wpa_cli commands
      5. On shutdown: kill the process, remove config, re-manage with NM

    This allows the primary adapter to stay connected to a router for internet
    while the secondary adapter handles Miracast P2P independently.
    """

    def __init__(self, interface: str, device_name: str = "Ubuntu Miracast Server"):
        """Initialize the manager.

        Args:
            interface: The Wi-Fi interface name (e.g., 'wlx3c78950c6ede').
            device_name: Device name to advertise via P2P.
        """
        self._interface = interface
        self._device_name = device_name
        self._process: subprocess.Popen | None = None
        self._ctrl_dir = _CTRL_DIR
        self._conf_path = _CONF_PATH
        self._log_path = _LOG_PATH
        self._was_nm_managed = False
        self._started = False

    @property
    def interface(self) -> str:
        """The Wi-Fi interface being managed."""
        return self._interface

    @property
    def ctrl_path(self) -> str:
        """The wpa_supplicant control socket directory.

        Use with: wpa_cli -p <ctrl_path> -i <interface> <command>
        """
        return self._ctrl_dir

    @property
    def is_running(self) -> bool:
        """Whether the dedicated wpa_supplicant process is running."""
        if self._process is None:
            return False
        return self._process.poll() is None

    def start(self) -> None:
        """Start the dedicated wpa_supplicant instance.

        Steps:
          1. Unmanage the interface from NetworkManager
          2. Write wpa_supplicant config
          3. Spawn the wpa_supplicant process
          4. Wait for the control socket to appear

        Raises:
            RuntimeError: If starting fails at any step.
        """
        if self._started:
            logger.debug("P2P supplicant already started")
            return

        logger.info("Starting dedicated wpa_supplicant on %s", self._interface)

        # Step 1: Unmanage from NetworkManager
        self._unmanage_from_nm()

        # Step 2: Write config file
        self._write_config()

        # Step 3: Create control socket directory
        os.makedirs(self._ctrl_dir, mode=0o755, exist_ok=True)

        # Step 4: Spawn wpa_supplicant
        try:
            self._process = subprocess.Popen(
                [
                    "sudo", "wpa_supplicant",
                    "-i", self._interface,
                    "-c", self._conf_path,
                    "-D", "nl80211",
                    "-f", self._log_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as e:
            self._remanage_with_nm()
            raise RuntimeError(f"Failed to start wpa_supplicant: {e}") from e

        # Step 5: Wait for control socket to appear
        if not self._wait_for_socket(timeout=5):
            self.stop()
            raise RuntimeError(
                f"wpa_supplicant started but control socket not created within 5 seconds. "
                f"Check {self._log_path} for errors."
            )

        self._started = True
        logger.info(
            "Dedicated wpa_supplicant running on %s (PID %d, ctrl=%s)",
            self._interface,
            self._process.pid,
            self._ctrl_dir,
        )

    def stop(self) -> None:
        """Stop the dedicated wpa_supplicant and restore NetworkManager management.

        Safe to call multiple times.
        """
        if not self._started and self._process is None:
            return

        logger.info("Stopping dedicated wpa_supplicant on %s", self._interface)

        # Kill the process
        if self._process and self._process.poll() is None:
            try:
                # Send SIGTERM via sudo since it runs as root
                subprocess.run(
                    ["sudo", "kill", str(self._process.pid)],
                    capture_output=True,
                    timeout=5,
                )
                self._process.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    subprocess.run(
                        ["sudo", "kill", "-9", str(self._process.pid)],
                        capture_output=True,
                        timeout=3,
                    )
                except (subprocess.TimeoutExpired, OSError):
                    pass

        self._process = None
        self._started = False

        # Restore NM management
        self._remanage_with_nm()

        # Clean up files
        self._cleanup_files()

        logger.info("Dedicated wpa_supplicant stopped, NM management restored")

    def run_wpa_cli(self, *args: str) -> str:
        """Run a wpa_cli command against the dedicated instance.

        Args:
            *args: Command arguments for wpa_cli.

        Returns:
            stdout output from wpa_cli.

        Raises:
            RuntimeError: If the command fails.
        """
        cmd = [
            "sudo", "wpa_cli",
            "-p", self._ctrl_dir,
            "-i", self._interface,
        ] + list(args)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"wpa_cli command failed: {' '.join(args)}: "
                    f"{result.stderr.strip() or result.stdout.strip()}"
                )
            return result.stdout.strip()
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"wpa_cli command timed out: {' '.join(args)}") from e

    def _unmanage_from_nm(self) -> None:
        """Tell NetworkManager to stop managing this interface."""
        try:
            result = subprocess.run(
                ["nmcli", "device", "set", self._interface, "managed", "no"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                self._was_nm_managed = True
                logger.debug("Unmanaged %s from NetworkManager", self._interface)
            else:
                logger.debug("nmcli unmanage returned %d: %s", result.returncode, result.stderr.strip())
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.debug("Could not unmanage from NM: %s", e)

    def _remanage_with_nm(self) -> None:
        """Restore NetworkManager management of this interface."""
        if not self._was_nm_managed:
            return
        try:
            subprocess.run(
                ["nmcli", "device", "set", self._interface, "managed", "yes"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            logger.debug("Restored NM management of %s", self._interface)
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.warning("Could not restore NM management: %s", e)

    def _write_config(self) -> None:
        """Write the wpa_supplicant configuration file."""
        config_content = _WPA_CONF_TEMPLATE.format(
            ctrl_dir=self._ctrl_dir,
            device_name=self._device_name,
        )
        try:
            # Write with sudo since /tmp may have sticky bit issues
            Path(self._conf_path).write_text(config_content)
            os.chmod(self._conf_path, 0o644)
            logger.debug("Wrote wpa_supplicant config to %s", self._conf_path)
        except OSError as e:
            raise RuntimeError(f"Failed to write wpa_supplicant config: {e}") from e

    def _wait_for_socket(self, timeout: float) -> bool:
        """Wait for the control socket to appear."""
        socket_path = os.path.join(self._ctrl_dir, self._interface)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.exists(socket_path):
                return True
            # Also check if process died
            if self._process and self._process.poll() is not None:
                logger.error(
                    "wpa_supplicant exited with code %d", self._process.returncode
                )
                return False
            time.sleep(0.2)
        return False

    def _cleanup_files(self) -> None:
        """Remove temporary config and socket files."""
        try:
            if os.path.exists(self._conf_path):
                os.unlink(self._conf_path)
        except OSError:
            pass

        try:
            socket_path = os.path.join(self._ctrl_dir, self._interface)
            if os.path.exists(socket_path):
                os.unlink(socket_path)
            if os.path.exists(self._ctrl_dir):
                os.rmdir(self._ctrl_dir)
        except OSError:
            pass
