"""Configuration management for Ubuntu Miracast Server."""

import json
import logging
import os
import stat
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Validation constraints for known keys
_VALIDATION_RULES = {
    ("streaming", "rtsp_port"): {"type": int, "min": 1024, "max": 65535},
    ("network", "go_intent"): {"type": int, "min": 0, "max": 15},
    ("network", "connection_timeout"): {"type": int, "min": 1, "max": 120},
    ("network", "rtp_port"): {"type": int, "min": 1024, "max": 65535},
}

_DEFAULT_CONFIG = {
    "general": {
        "device_name": "Ubuntu Miracast Server",
        "start_minimized": False,
        "fullscreen_on_stream": True,
        "log_level": "INFO",
    },
    "streaming": {
        "rtsp_port": 7236,
        "audio_enabled": True,
        "max_resolution": "1920x1080",
        "preferred_codec": "H264",
    },
    "network": {
        "go_intent": 15,
        "connection_timeout": 30,
        "auto_accept": True,
        "rtp_port": 1028,
        "p2p_interface": "",
        "listen_channel": 0,
    },
    "display": {
        "preferred_resolution": "1920x1080",
        "show_stream_info": True,
        "hw_accel": True,
    },
    "advanced": {
        "session_timeout": 30,
        "keep_alive_interval": 15,
        "buffer_size_ms": 100,
    },
    "service": {
        "enabled": False,
        "virtual_display": False,
        "idle_timeout": 0,
    },
}


class ServerConfig:
    """Manages server configuration with validation and JSON persistence."""

    def __init__(self, config_path: str | None = None):
        """Initialize the configuration manager.

        Args:
            config_path: Optional path to the config file. If not provided,
                         defaults to ~/.config/ubuntu-miracast-server/config.json.
        """
        if config_path:
            self.config_path = Path(config_path)
        else:
            self.config_path = (
                Path.home() / ".config" / "ubuntu-miracast-server" / "config.json"
            )

        # Create directory if it doesn't exist
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Load or create config
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """Load configuration from file or create default.

        If the file exists but contains malformed JSON, log a warning and
        fall back to defaults.
        """
        if self.config_path.exists():
            try:
                with open(self.config_path, "r") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    logger.warning(
                        "Config file %s does not contain a JSON object, using defaults",
                        self.config_path,
                    )
                    return self._create_default_config()
                return data
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(
                    "Malformed JSON in config file %s: %s — using defaults",
                    self.config_path,
                    e,
                )
                return self._create_default_config()
            except OSError as e:
                logger.error("Failed to read config file %s: %s", self.config_path, e)
                return self._create_default_config()
        else:
            return self._create_default_config()

    def _create_default_config(self) -> dict:
        """Create and persist default configuration."""
        import copy

        config = copy.deepcopy(_DEFAULT_CONFIG)
        try:
            self._write_config(config)
        except Exception as e:
            logger.error("Failed to save default config: %s", e)
        return config

    def _write_config(self, config: dict) -> None:
        """Write configuration to disk with 0600 permissions.

        Args:
            config: The configuration dictionary to persist.

        Raises:
            OSError: If writing fails.
        """
        # Ensure parent directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to a temporary file then rename for atomicity
        tmp_path = self.config_path.with_suffix(".tmp")
        try:
            # Create file with restricted permissions
            fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(config, f, indent=2)
            except Exception:
                # fd is consumed by fdopen even on error
                raise
            # Rename atomically
            tmp_path.rename(self.config_path)
        except Exception:
            # Clean up temp file on failure
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise

        # Ensure final file has correct permissions (in case rename preserved old perms)
        try:
            os.chmod(str(self.config_path), stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def _validate(self, section: str, key: str, value: Any) -> None:
        """Validate a value against known constraints.

        Args:
            section: Configuration section name.
            key: Configuration key name.
            value: The value to validate.

        Raises:
            ValueError: If the value violates constraints.
        """
        rule = _VALIDATION_RULES.get((section, key))
        if rule is None:
            return

        expected_type = rule["type"]
        if not isinstance(value, expected_type):
            raise ValueError(
                f"{section}.{key} must be {expected_type.__name__}, got {type(value).__name__}"
            )

        min_val = rule.get("min")
        max_val = rule.get("max")
        if min_val is not None and value < min_val:
            raise ValueError(
                f"{section}.{key} must be >= {min_val}, got {value}"
            )
        if max_val is not None and value > max_val:
            raise ValueError(
                f"{section}.{key} must be <= {max_val}, got {value}"
            )

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Get a configuration value.

        Args:
            section: Configuration section (e.g. "general", "streaming").
            key: Configuration key within the section.
            default: Default value if the key doesn't exist.

        Returns:
            The configuration value, or default if not found.
        """
        try:
            return self.config[section][key]
        except KeyError:
            return default

    def set(self, section: str, key: str, value: Any) -> None:
        """Set a configuration value with validation.

        Validates the value against known constraints before applying.
        On successful validation, updates the in-memory config and persists
        to disk. If disk write fails, the value is still retained in memory.

        Args:
            section: Configuration section.
            key: Configuration key.
            value: Value to set.

        Raises:
            ValueError: If the value fails validation (previous value is retained).
        """
        # Validate before applying
        self._validate(section, key, value)

        # Create section if it doesn't exist
        if section not in self.config:
            self.config[section] = {}

        self.config[section][key] = value

        # Persist to disk (retain in memory even if write fails)
        try:
            self._write_config(self.config)
        except OSError as e:
            logger.error(
                "Failed to persist config after setting %s.%s: %s", section, key, e
            )

    def save(self, config: dict | None = None) -> None:
        """Save configuration to file.

        Args:
            config: Configuration to save. If not provided, saves the current
                    in-memory configuration.
        """
        if config is not None:
            self.config = config

        try:
            self._write_config(self.config)
        except OSError as e:
            logger.error("Failed to save config: %s", e)
