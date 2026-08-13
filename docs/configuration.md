# Configuration Reference

Ubuntu Miracast Server stores its configuration in JSON format at:

```
~/.config/ubuntu-miracast-server/config.json
```

The file is created automatically on first run with default values. It uses 0600 permissions (user-only read/write).

## Configuration Sections

### `general` — Application Behavior

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `device_name` | string | `"Ubuntu Miracast Server"` | Name advertised to Miracast source devices |
| `start_minimized` | bool | `false` | Start the application minimized to tray |
| `fullscreen_on_stream` | bool | `true` | Automatically enter fullscreen when a stream starts |
| `log_level` | string | `"INFO"` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

### `streaming` — Media Configuration

| Key | Type | Default | Validation | Description |
|-----|------|---------|------------|-------------|
| `rtsp_port` | int | `7236` | 1024–65535 | TCP port for RTSP control session |
| `audio_enabled` | bool | `true` | — | Enable AAC audio decoding |
| `max_resolution` | string | `"1920x1080"` | — | Maximum accepted resolution |
| `preferred_codec` | string | `"H264"` | — | Preferred video codec |

### `network` — Connection Settings

| Key | Type | Default | Validation | Description |
|-----|------|---------|------------|-------------|
| `go_intent` | int | `15` | 0–15 | P2P Group Owner intent (higher = prefer being GO) |
| `connection_timeout` | int | `30` | 1–120 | Seconds to wait for P2P group formation |
| `auto_accept` | bool | `true` | — | Automatically accept incoming connection requests |
| `rtp_port` | int | `1028` | 1024–65535 | UDP port for RTP media reception |
| `p2p_interface` | string | `""` | — | Override P2P interface (auto-detected if empty) |
| `listen_channel` | int | `0` | — | P2P listen channel (0 = auto) |

### `display` — Visual Preferences

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `preferred_resolution` | string | `"1920x1080"` | Preferred display resolution |
| `show_stream_info` | bool | `true` | Show resolution/bitrate overlay during playback |
| `hw_accel` | bool | `true` | Attempt hardware-accelerated video decoding |

### `advanced` — Protocol Tuning

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `session_timeout` | int | `30` | RTSP session inactivity timeout (seconds) |
| `keep_alive_interval` | int | `15` | RTSP keep-alive interval (seconds) |
| `buffer_size_ms` | int | `100` | Receive buffer target latency (milliseconds) |

### `service` — Service Mode

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | `false` | Whether service mode is enabled |
| `virtual_display` | bool | `false` | Use a virtual display in service mode |
| `idle_timeout` | int | `0` | Exit service after N seconds idle (0 = never) |

## Validation Rules

Values are validated on `set()`. Invalid values raise `ValueError` and the previous value is retained.

| Key | Rule |
|-----|------|
| `streaming.rtsp_port` | Integer, 1024 ≤ value ≤ 65535 |
| `network.go_intent` | Integer, 0 ≤ value ≤ 15 |
| `network.connection_timeout` | Integer, 1 ≤ value ≤ 120 |
| `network.rtp_port` | Integer, 1024 ≤ value ≤ 65535 |

## Example Configuration

```json
{
  "general": {
    "device_name": "Living Room Display",
    "start_minimized": false,
    "fullscreen_on_stream": true,
    "log_level": "INFO"
  },
  "streaming": {
    "rtsp_port": 7236,
    "audio_enabled": true,
    "max_resolution": "1920x1080",
    "preferred_codec": "H264"
  },
  "network": {
    "go_intent": 15,
    "connection_timeout": 30,
    "auto_accept": true,
    "rtp_port": 1028,
    "p2p_interface": "",
    "listen_channel": 0
  },
  "display": {
    "preferred_resolution": "1920x1080",
    "show_stream_info": true,
    "hw_accel": true
  },
  "advanced": {
    "session_timeout": 30,
    "keep_alive_interval": 15,
    "buffer_size_ms": 100
  },
  "service": {
    "enabled": false,
    "virtual_display": false,
    "idle_timeout": 0
  }
}
```

## Error Handling

- **Malformed JSON on load:** A warning is logged, defaults are used, and the file is not overwritten until the next explicit `set()` or `save()`.
- **Disk write failure:** The value is retained in memory, an error is logged, and no exception is raised to the caller.
- **Missing config file:** Created automatically with defaults and 0600 permissions.

## Programmatic Access

```python
from miracast_server.config import ServerConfig

config = ServerConfig()

# Read
port = config.get("streaming", "rtsp_port", 7236)
name = config.get("general", "device_name", "default")

# Write (validates before applying)
config.set("streaming", "rtsp_port", 8000)

# Invalid values raise ValueError
config.set("network", "go_intent", 99)  # ValueError: must be <= 15
```
