"""Tests for ServerConfig configuration management."""

import json
import os
import stat
from unittest.mock import patch

import pytest

from miracast_server.config import ServerConfig


class TestServerConfigDefaults:
    """Test default configuration generation."""

    def test_creates_default_config_when_no_file_exists(self, tmp_path):
        config_file = tmp_path / "config.json"
        ServerConfig(config_path=str(config_file))

        assert config_file.exists()
        with open(config_file) as f:
            data = json.load(f)

        assert data["general"]["device_name"] == "Ubuntu Miracast Server"
        assert data["general"]["start_minimized"] is False
        assert data["general"]["fullscreen_on_stream"] is True
        assert data["general"]["log_level"] == "INFO"

    def test_default_streaming_section(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        assert cfg.get("streaming", "rtsp_port") == 7236
        assert cfg.get("streaming", "audio_enabled") is True
        assert cfg.get("streaming", "max_resolution") == "1920x1080"
        assert cfg.get("streaming", "preferred_codec") == "H264"

    def test_default_network_section(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        assert cfg.get("network", "go_intent") == 15
        assert cfg.get("network", "connection_timeout") == 30
        assert cfg.get("network", "auto_accept") is True

    def test_default_service_section(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        assert cfg.get("service", "enabled") is False
        assert cfg.get("service", "virtual_display") is False
        assert cfg.get("service", "idle_timeout") == 0

    def test_creates_parent_directories(self, tmp_path):
        config_file = tmp_path / "subdir" / "nested" / "config.json"
        ServerConfig(config_path=str(config_file))

        assert config_file.exists()


class TestServerConfigFilePermissions:
    """Test that config files are created with 0600 permissions."""

    def test_default_config_has_0600_permissions(self, tmp_path):
        config_file = tmp_path / "config.json"
        ServerConfig(config_path=str(config_file))

        file_stat = os.stat(config_file)
        mode = stat.S_IMODE(file_stat.st_mode)
        assert mode == 0o600

    def test_saved_config_has_0600_permissions(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        cfg.set("general", "device_name", "New Name")

        file_stat = os.stat(config_file)
        mode = stat.S_IMODE(file_stat.st_mode)
        assert mode == 0o600


class TestServerConfigGetSet:
    """Test get and set operations."""

    def test_get_existing_key(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        assert cfg.get("general", "device_name") == "Ubuntu Miracast Server"

    def test_get_missing_key_returns_default(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        assert cfg.get("general", "nonexistent") is None
        assert cfg.get("general", "nonexistent", "fallback") == "fallback"

    def test_get_missing_section_returns_default(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        assert cfg.get("nonexistent_section", "key") is None
        assert cfg.get("nonexistent_section", "key", 42) == 42

    def test_set_then_get_returns_same_value(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        cfg.set("general", "device_name", "My Display")
        assert cfg.get("general", "device_name") == "My Display"

    def test_set_creates_new_section(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        cfg.set("custom", "key", "value")
        assert cfg.get("custom", "key") == "value"

    def test_set_persists_to_disk(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        cfg.set("general", "device_name", "Persisted Name")

        # Read fresh from disk
        with open(config_file) as f:
            data = json.load(f)
        assert data["general"]["device_name"] == "Persisted Name"

    def test_get_with_default_does_not_modify_file(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        # Record file content before
        with open(config_file) as f:
            before = f.read()

        # Access missing key with default
        result = cfg.get("general", "nonexistent_key", "some_default")
        assert result == "some_default"

        # File should be unchanged
        with open(config_file) as f:
            after = f.read()
        assert before == after


class TestServerConfigValidation:
    """Test value validation for constrained keys."""

    def test_rtsp_port_valid_min(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        cfg.set("streaming", "rtsp_port", 1024)
        assert cfg.get("streaming", "rtsp_port") == 1024

    def test_rtsp_port_valid_max(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        cfg.set("streaming", "rtsp_port", 65535)
        assert cfg.get("streaming", "rtsp_port") == 65535

    def test_rtsp_port_below_min_rejected(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        with pytest.raises(ValueError):
            cfg.set("streaming", "rtsp_port", 1023)
        # Previous value retained
        assert cfg.get("streaming", "rtsp_port") == 7236

    def test_rtsp_port_above_max_rejected(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        with pytest.raises(ValueError):
            cfg.set("streaming", "rtsp_port", 65536)
        assert cfg.get("streaming", "rtsp_port") == 7236

    def test_rtsp_port_wrong_type_rejected(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        with pytest.raises(ValueError):
            cfg.set("streaming", "rtsp_port", "8080")
        assert cfg.get("streaming", "rtsp_port") == 7236

    def test_go_intent_valid_range(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        cfg.set("network", "go_intent", 0)
        assert cfg.get("network", "go_intent") == 0

        cfg.set("network", "go_intent", 15)
        assert cfg.get("network", "go_intent") == 15

    def test_go_intent_below_min_rejected(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        with pytest.raises(ValueError):
            cfg.set("network", "go_intent", -1)
        assert cfg.get("network", "go_intent") == 15

    def test_go_intent_above_max_rejected(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        with pytest.raises(ValueError):
            cfg.set("network", "go_intent", 16)
        assert cfg.get("network", "go_intent") == 15

    def test_connection_timeout_valid_range(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        cfg.set("network", "connection_timeout", 1)
        assert cfg.get("network", "connection_timeout") == 1

        cfg.set("network", "connection_timeout", 120)
        assert cfg.get("network", "connection_timeout") == 120

    def test_connection_timeout_below_min_rejected(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        with pytest.raises(ValueError):
            cfg.set("network", "connection_timeout", 0)
        assert cfg.get("network", "connection_timeout") == 30

    def test_connection_timeout_above_max_rejected(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        with pytest.raises(ValueError):
            cfg.set("network", "connection_timeout", 121)
        assert cfg.get("network", "connection_timeout") == 30

    def test_unconstrained_keys_accept_any_value(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        # device_name has no constraints
        cfg.set("general", "device_name", 12345)
        assert cfg.get("general", "device_name") == 12345

        cfg.set("general", "device_name", None)
        assert cfg.get("general", "device_name") is None


class TestServerConfigMalformedJSON:
    """Test handling of malformed JSON in config file."""

    def test_malformed_json_uses_defaults(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text("{invalid json content")

        cfg = ServerConfig(config_path=str(config_file))

        # Should fall back to defaults
        assert cfg.get("general", "device_name") == "Ubuntu Miracast Server"
        assert cfg.get("streaming", "rtsp_port") == 7236

    def test_empty_file_uses_defaults(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text("")

        cfg = ServerConfig(config_path=str(config_file))

        assert cfg.get("general", "device_name") == "Ubuntu Miracast Server"

    def test_non_dict_json_uses_defaults(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text("[1, 2, 3]")

        cfg = ServerConfig(config_path=str(config_file))

        assert cfg.get("general", "device_name") == "Ubuntu Miracast Server"

    def test_valid_json_loaded_correctly(self, tmp_path):
        config_file = tmp_path / "config.json"
        custom_config = {
            "general": {"device_name": "Custom Server"},
            "streaming": {"rtsp_port": 8080},
        }
        config_file.write_text(json.dumps(custom_config))

        cfg = ServerConfig(config_path=str(config_file))

        assert cfg.get("general", "device_name") == "Custom Server"
        assert cfg.get("streaming", "rtsp_port") == 8080


class TestServerConfigDiskWriteFailure:
    """Test that disk write failures retain config in memory."""

    def test_set_retains_value_on_write_failure(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        # Make directory read-only to prevent writes
        with patch.object(cfg, "_write_config", side_effect=OSError("Disk full")):
            cfg.set("general", "device_name", "Memory Only")

        # Value is still in memory
        assert cfg.get("general", "device_name") == "Memory Only"

    def test_save_does_not_raise_on_write_failure(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        with patch.object(cfg, "_write_config", side_effect=OSError("Disk full")):
            # Should not raise
            cfg.save()

    def test_set_validation_failure_does_not_change_value(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        original_port = cfg.get("streaming", "rtsp_port")
        with pytest.raises(ValueError):
            cfg.set("streaming", "rtsp_port", 999)

        # Value unchanged both in memory and on disk
        assert cfg.get("streaming", "rtsp_port") == original_port
        with open(config_file) as f:
            data = json.load(f)
        assert data["streaming"]["rtsp_port"] == original_port


class TestServerConfigSave:
    """Test the save method."""

    def test_save_current_config(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        cfg.config["general"]["device_name"] = "Direct Modify"
        cfg.save()

        with open(config_file) as f:
            data = json.load(f)
        assert data["general"]["device_name"] == "Direct Modify"

    def test_save_with_new_config(self, tmp_path):
        config_file = tmp_path / "config.json"
        cfg = ServerConfig(config_path=str(config_file))

        new_config = {"custom": {"key": "value"}}
        cfg.save(new_config)

        assert cfg.config == new_config
        with open(config_file) as f:
            data = json.load(f)
        assert data == new_config


class TestServerConfigLoadExisting:
    """Test loading existing configuration from disk."""

    def test_loads_existing_config(self, tmp_path):
        config_file = tmp_path / "config.json"
        existing = {
            "general": {"device_name": "Preexisting Server", "log_level": "DEBUG"},
            "streaming": {"rtsp_port": 9000},
        }
        config_file.write_text(json.dumps(existing))

        cfg = ServerConfig(config_path=str(config_file))

        assert cfg.get("general", "device_name") == "Preexisting Server"
        assert cfg.get("general", "log_level") == "DEBUG"
        assert cfg.get("streaming", "rtsp_port") == 9000

    def test_missing_sections_return_default(self, tmp_path):
        config_file = tmp_path / "config.json"
        # Only general section exists
        existing = {"general": {"device_name": "Partial Config"}}
        config_file.write_text(json.dumps(existing))

        cfg = ServerConfig(config_path=str(config_file))

        assert cfg.get("general", "device_name") == "Partial Config"
        # Missing sections return None (not defaults)
        assert cfg.get("streaming", "rtsp_port") is None
        assert cfg.get("streaming", "rtsp_port", 7236) == 7236
