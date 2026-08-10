# API & Module Specification

## Ubuntu Miracast Server (Sink) v1.0.0

**Document Version:** 1.0  
**Date:** 2026-08-10  
**Status:** Draft

---

## 1. Module Overview

| Module | File | Purpose |
|--------|------|---------|
| `miracast_server` | `__init__.py` | Package root, version declaration |
| `miracast_server.app` | `app.py` | Application entry point and GTK app class |
| `miracast_server.sink` | `sink.py` | Central orchestrator (MiracastSink) |
| `miracast_server.p2p_advertiser` | `p2p_advertiser.py` | Wi-Fi Direct P2P advertisement and connection |
| `miracast_server.rtsp_server` | `rtsp_server.py` | RTSP/WFD protocol server |
| `miracast_server.media_receiver` | `media_receiver.py` | GStreamer receive/decode pipeline |
| `miracast_server.config` | `config.py` | Configuration management |
| `miracast_server.service` | `service.py` | Systemd service management |
| `miracast_server.ui.display_window` | `ui/display_window.py` | Main display window |
| `miracast_server.ui.status_view` | `ui/status_view.py` | Connection status widget |
| `miracast_server.ui.settings_view` | `ui/settings_view.py` | Settings page |
| `miracast_server.ui.stream_info` | `ui/stream_info.py` | Stream info overlay |

---

## 2. Core Module APIs

### 2.1 `miracast_server.sink`

#### Class: `MiracastSink(GObject.Object)`

The central orchestrator that coordinates P2P advertising, RTSP negotiation, and media reception.

**Constructor:**

```python
class MiracastSink(GObject.Object):
    def __init__(self, config: Config):
        """
        Initialize the Miracast sink orchestrator.

        Args:
            config: Application configuration instance
        """
```

**Public Methods:**

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `start()` | — | `None` | Begin advertising as WFD sink (enters Advertising state) |
| `stop()` | — | `None` | Stop advertising and disconnect any active session |
| `disconnect()` | — | `None` | Disconnect current source, return to Advertising |
| `get_state()` | — | `SinkState` | Get current state |
| `get_source_info()` | — | `Optional[SourceInfo]` | Get connected source device info |
| `get_stream_stats()` | — | `Optional[StreamStats]` | Get current stream statistics |
| `get_paintable()` | — | `Optional[Gdk.Paintable]` | Get GStreamer video paintable for GTK display |

**GObject Signals:**

| Signal | Signature | Description |
|--------|-----------|-------------|
| `state-changed` | `(int,)` | Emitted when sink state changes (SinkState enum value) |
| `source-connected` | `(object,)` | Emitted with SourceInfo when a source connects |
| `source-disconnected` | `()` | Emitted when source disconnects |
| `stream-started` | `(object,)` | Emitted with StreamInfo when media begins |
| `stream-stopped` | `()` | Emitted when media stream stops |
| `stats-updated` | `(object,)` | Emitted with StreamStats periodically |
| `error` | `(str,)` | Emitted with error description |

**Enums:**

```python
class SinkState(IntEnum):
    IDLE = 0
    ADVERTISING = 1
    CONNECTING = 2
    NEGOTIATING = 3
    STREAMING = 4
    DISCONNECTED = 5
```

**Data Classes:**

```python
@dataclass
class SourceInfo:
    name: str           # Source device friendly name
    address: str        # P2P MAC address
    ip_address: str     # IP address after DHCP

@dataclass
class StreamInfo:
    video_format: str   # e.g., "1920x1080p30"
    audio_codec: str    # e.g., "AAC-LC 48kHz stereo"
    rtp_port: int       # Negotiated RTP port

@dataclass
class StreamStats:
    bitrate_kbps: float     # Current bitrate in kbps
    frame_rate: float       # Current decoded frame rate
    resolution: str         # Current resolution string
    packets_received: int   # Total RTP packets received
    packets_lost: int       # Estimated packet loss
    duration_seconds: int   # Stream duration
    audio_level_db: float   # Current audio level
```

---

### 2.2 `miracast_server.p2p_advertiser`

#### Class: `P2PAdvertiser(GObject.Object)`

**Constructor:**

```python
class P2PAdvertiser(GObject.Object):
    def __init__(self, interface: str = "wlan0", rtsp_port: int = 7236, device_name: str = ""):
        """
        Initialize P2P advertiser.

        Args:
            interface: Wi-Fi interface name supporting P2P
            rtsp_port: RTSP port to advertise in WFD sub-elements
            device_name: Friendly name to advertise (default: hostname)
        """
```

**Public Methods:**

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `start_advertising()` | — | `None` | Set wfd_subelems, enter P2P listen state |
| `stop_advertising()` | — | `None` | Exit P2P listen, clear wfd_subelems |
| `accept_connection(peer_addr)` | `peer_addr: str` | `None` | Accept P2P connection from peer |
| `reject_connection()` | — | `None` | Reject pending P2P connection request |
| `disconnect_peer()` | — | `None` | Disconnect current P2P peer, remove group |
| `get_peer_ip()` | — | `Optional[str]` | Get IP address of connected peer |
| `get_p2p_interface()` | — | `Optional[str]` | Get name of P2P group interface (e.g., p2p-wlan0-0) |
| `is_advertising()` | — | `bool` | Check if currently in listen state |

**GObject Signals:**

| Signal | Signature | Description |
|--------|-----------|-------------|
| `connection-requested` | `(str, str)` | Emitted with (peer_addr, peer_name) when source requests connection |
| `group-formed` | `(str, str, bool)` | Emitted with (interface, peer_addr, is_go) when P2P group starts |
| `ip-assigned` | `(str, str)` | Emitted with (local_ip, peer_ip) after DHCP completes |
| `peer-disconnected` | `()` | Emitted when P2P peer disconnects or group is removed |
| `advertiser-error` | `(str,)` | Emitted with error message |

---

### 2.3 `miracast_server.rtsp_server`

#### Class: `RTSPServer`

**Constructor:**

```python
class RTSPServer:
    def __init__(self, port: int = 7236, rtp_port: int = 1028, capabilities: WFDCapabilities = None):
        """
        Initialize RTSP/WFD server.

        Args:
            port: TCP port to listen on
            rtp_port: UDP port for RTP media reception (advertised in wfd_client_rtp_ports)
            capabilities: WFD sink capabilities to advertise
        """
```

**Public Methods:**

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `start(bind_address)` | `bind_address: str = "0.0.0.0"` | `None` | Start TCP server in background thread |
| `stop()` | — | `None` | Stop server, close all connections |
| `send_request(method, uri, headers, body)` | `method: str, uri: str, headers: dict, body: str` | `None` | Send RTSP request to connected source (for M2) |
| `get_session_id()` | — | `Optional[str]` | Get active RTSP session ID |
| `get_negotiated_params()` | — | `Optional[NegotiatedParams]` | Get negotiated stream parameters |
| `is_running()` | — | `bool` | Check if server is listening |

**Callback Setters:**

| Method | Callback Signature | Description |
|--------|-------------------|-------------|
| `on_options_received(cb)` | `cb(cseq: int)` | Called when M1 OPTIONS received |
| `on_get_parameter(cb)` | `cb(params: list[str]) -> dict` | Called for M3; return capability values |
| `on_set_parameter(cb)` | `cb(params: dict) -> bool` | Called for M4; return True to accept |
| `on_setup(cb)` | `cb(transport: str) -> (str, str)` | Called for M5; return (session_id, server_transport) |
| `on_play(cb)` | `cb(session_id: str)` | Called for M6 |
| `on_teardown(cb)` | `cb(session_id: str)` | Called for M7 |
| `on_client_connected(cb)` | `cb(addr: str)` | Called when source TCP connects |
| `on_client_disconnected(cb)` | `cb()` | Called when source TCP disconnects |

**Data Classes:**

```python
@dataclass
class WFDCapabilities:
    """Sink capabilities advertised in M3 GET_PARAMETER response."""
    # Video
    supported_cea_resolutions: int      # Bitmap: CEA resolution table
    supported_vesa_resolutions: int     # Bitmap: VESA resolution table
    supported_hh_resolutions: int       # Bitmap: Handheld resolution table
    preferred_resolution_index: int     # Native resolution index in CEA table
    h264_profile: int                   # 0x01=CBP, 0x02=CHP
    h264_level: int                     # 0x01=3.1, 0x02=3.2, 0x04=4, 0x08=4.1, 0x10=4.2
    # Audio
    audio_codecs: int                   # Bitmap: 0x01=LPCM, 0x02=AAC, 0x04=AC3
    audio_sampling_rates: int           # Bitmap: 0x01=44.1kHz, 0x02=48kHz
    audio_channels: int                 # 2 (stereo), 6 (5.1), 8 (7.1)
    # Transport
    rtp_port: int                       # UDP port for RTP reception

@dataclass
class NegotiatedParams:
    """Parameters agreed upon during M4 SET_PARAMETER."""
    video_codec: str            # "H264"
    video_profile: str          # "CBP" or "CHP"
    video_level: str            # "3.1", "4.1", etc.
    video_resolution: str       # "1920x1080"
    video_framerate: int        # 30 or 60
    audio_codec: str            # "AAC"
    audio_sample_rate: int      # 44100 or 48000
    audio_channels: int         # 2
    presentation_url: str       # wfd_presentation_URL from source
```

#### Class: `RTSPMessage`

```python
@dataclass
class RTSPMessage:
    """Parsed RTSP message (request or response)."""
    is_request: bool
    method: str = ""            # For requests: OPTIONS, GET_PARAMETER, etc.
    uri: str = ""               # For requests: rtsp://... or *
    status_code: int = 0        # For responses: 200, 400, etc.
    status_text: str = ""       # For responses: "OK", "Bad Request", etc.
    headers: dict = field(default_factory=dict)  # CSeq, Content-Type, etc.
    body: str = ""              # Message body

    @classmethod
    def parse(cls, data: bytes) -> "RTSPMessage":
        """Parse raw RTSP data into message object."""

    def serialize(self) -> bytes:
        """Serialize message to bytes for transmission."""
```

---

### 2.4 `miracast_server.media_receiver`

#### Class: `MediaReceiver(GObject.Object)`

**Constructor:**

```python
class MediaReceiver(GObject.Object):
    def __init__(self, rtp_port: int = 1028, use_hw_accel: bool = True, headless: bool = False):
        """
        Initialize media receiver with GStreamer pipeline.

        Args:
            rtp_port: UDP port for RTP media reception
            use_hw_accel: Attempt hardware-accelerated decoding
            headless: If True, use autovideosink instead of gtk4paintablesink
        """
```

**Public Methods:**

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `start()` | — | `None` | Set pipeline to PLAYING state |
| `stop()` | — | `None` | Set pipeline to NULL state, cleanup |
| `pause()` | — | `None` | Set pipeline to PAUSED state |
| `get_paintable()` | — | `Optional[Gdk.Paintable]` | Get GdkPaintable from gtk4paintablesink (None if headless) |
| `get_stats()` | — | `StreamStats` | Get current stream statistics |
| `set_mute(muted)` | `muted: bool` | `None` | Mute/unmute audio output |
| `set_volume(level)` | `level: float` | `None` | Set audio volume (0.0–1.0) |
| `is_playing()` | — | `bool` | Check if pipeline is in PLAYING state |

**GObject Signals:**

| Signal | Signature | Description |
|--------|-----------|-------------|
| `pipeline-started` | `()` | Emitted when pipeline reaches PLAYING state |
| `pipeline-stopped` | `()` | Emitted when pipeline reaches NULL state |
| `pipeline-error` | `(str,)` | Emitted with error message from GStreamer bus |
| `stream-info-changed` | `(object,)` | Emitted with StreamInfo when format is detected/changed |
| `stats-updated` | `(object,)` | Emitted with StreamStats (every ~1 second) |

**Internal Methods:**

| Method | Description |
|--------|-------------|
| `_build_pipeline()` | Construct GStreamer pipeline string and create elements |
| `_on_bus_message(bus, message)` | Handle GStreamer bus messages (ERROR, WARNING, EOS, STATE_CHANGED) |
| `_on_pad_added(element, pad)` | Handle dynamic pad creation from tsdemux |
| `_collect_stats()` | Periodic stats collection from pipeline elements |

---

### 2.5 `miracast_server.config`

#### Class: `Config`

**Constructor:**

```python
class Config:
    def __init__(self, config_path: str = None):
        """
        Initialize configuration manager.

        Args:
            config_path: Path to config JSON file.
                         Default: ~/.config/ubuntu-miracast-server/config.json
        """
```

**Public Methods:**

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `get(section, key, default)` | `section: str, key: str, default: Any = None` | `Any` | Get config value or default |
| `set(section, key, value)` | `section: str, key: str, value: Any` | `None` | Set config value (creates section if needed) |
| `save(config)` | `config: dict = None` | `None` | Save current config to disk |
| `get_device_name()` | — | `str` | Shortcut: get general.device_name (falls back to hostname) |
| `get_rtsp_port()` | — | `int` | Shortcut: get network.rtsp_port |
| `get_rtp_port()` | — | `int` | Shortcut: get network.rtp_port |
| `get_interface()` | — | `str` | Shortcut: get network.p2p_interface |

---

### 2.6 `miracast_server.service`

#### Class: `ServiceManager`

**Constants:**
- `SERVICE_NAME = "ubuntu-miracast-server"`
- `SERVICE_FILE = "ubuntu-miracast-server.service"`

**Constructor:**

```python
class ServiceManager:
    def __init__(self):
        """Initialize service manager."""
```

**Public Methods:**

| Method | Parameters | Returns | Raises | Description |
|--------|-----------|---------|--------|-------------|
| `is_service_enabled()` | — | `bool` | — | Check if service is enabled via systemctl |
| `is_service_running()` | — | `bool` | — | Check if service is active via systemctl |
| `enable_service()` | — | `None` | `RuntimeError` | Create service file, daemon-reload, enable |
| `disable_service()` | — | `None` | `RuntimeError` | Stop, disable, remove file, daemon-reload |
| `start_service()` | — | `None` | `RuntimeError` | Start service (enables if needed) |
| `stop_service()` | — | `None` | `RuntimeError` | Stop service |

#### Function: `run_as_service(device_name: str = None)`

```python
def run_as_service(device_name: str = None) -> int:
    """
    Run the Miracast sink in headless service mode.

    Creates MiracastSink with headless MediaReceiver, starts advertising,
    and runs GLib.MainLoop until terminated.

    Args:
        device_name: Override device name from CLI (--name flag)

    Returns:
        Exit code (0 for clean exit)
    """
```

---

## 3. UI Module APIs

### 3.1 `miracast_server.ui.display_window`

#### Class: `DisplayWindow(Adw.ApplicationWindow)`

**Constructor:**

```python
class DisplayWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application, sink: MiracastSink):
        """
        Initialize the display window.

        Args:
            application: Parent GTK application
            sink: MiracastSink orchestrator instance
        """
```

**Public Methods:**

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `set_fullscreen_mode(enabled)` | `enabled: bool` | `None` | Enter/exit fullscreen |
| `toggle_fullscreen()` | — | `None` | Toggle fullscreen state |
| `show_video()` | — | `None` | Switch stack to video page, bind paintable |
| `show_waiting()` | — | `None` | Switch stack to waiting page |
| `update_status(text)` | `text: str` | `None` | Update header bar status label |

**Key Bindings:**

| Key | Action |
|-----|--------|
| F11 | Toggle fullscreen |
| Escape | Exit fullscreen |
| Double-click on video | Toggle fullscreen |

**Actions (Gio.SimpleAction):**

| Action | Description |
|--------|-------------|
| `fullscreen` | Toggle fullscreen mode |
| `disconnect` | Disconnect current source |
| `settings` | Show settings page |
| `about` | Show about dialog |
| `quit` | Quit application |

### 3.2 `miracast_server.ui.status_view`

#### Class: `StatusView(Gtk.Box)`

**Constructor:** `StatusView(sink: MiracastSink)`

**Behavior:**
- Displays large status icon and text based on sink state
- Shows spinner during Connecting/Negotiating states
- Shows device name when connected
- Provides "Start Advertising" / "Stop" button

### 3.3 `miracast_server.ui.settings_view`

#### Class: `SettingsView(Gtk.Box)`

**Constructor:** `SettingsView(config: Config, service_manager: ServiceManager)`

**Settings Groups:**

| Group | Controls |
|-------|----------|
| General | Device name (entry), Auto-accept connections (switch), Log level (dropdown) |
| Network | RTSP port (spin), RTP port (spin), P2P interface (entry) |
| Display | Preferred resolution (dropdown), Show stream info (switch), Hardware acceleration (switch) |
| Service | Run as service (switch), Status label, Start/Stop buttons |

### 3.4 `miracast_server.ui.stream_info`

#### Class: `StreamInfoOverlay(Gtk.Box)`

**Constructor:** `StreamInfoOverlay()`

**Public Methods:**

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `update(stats)` | `stats: StreamStats` | `None` | Update displayed statistics |
| `set_visible(visible)` | `visible: bool` | `None` | Show/hide overlay |

**Displayed Info:**
- Resolution (e.g., "1920×1080p30")
- Bitrate (e.g., "8.5 Mbps")
- Packet loss percentage
- Stream duration

---

## 4. Application Entry Point

### 4.1 `miracast_server.app`

#### Class: `MiracastServerApp(Adw.Application)`

**Application ID:** `com.ubuntu.miracast-server`

**Constructor:**

```python
class MiracastServerApp(Adw.Application):
    def __init__(self):
        """Initialize the Miracast Server application."""
```

Instantiates: Config, MiracastSink, ServiceManager

**Lifecycle:**
- `do_activate()` → Creates DisplayWindow, connects MiracastSink signals, auto-starts advertising
- `do_shutdown()` → Stops MiracastSink, cleanup

#### Function: `main()`

```python
def main() -> int:
    """
    Application entry point.

    CLI Arguments:
        --service       Run in headless service mode (no GTK window)
        --fullscreen    Start in fullscreen mode
        --name NAME     Override advertised device name

    Returns:
        Exit code
    """
```

**CLI Argument Parsing:**

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--service` | flag | False | Run headless with GLib.MainLoop |
| `--fullscreen` | flag | False | Start display window in fullscreen |
| `--name` | string | (from config) | Override the WFD device name |
| `--port` | int | 7236 | Override RTSP port |
| `--interface` | string | wlan0 | Override P2P Wi-Fi interface |

**Console Script Entry Point:** `ubuntu-miracast-server = miracast_server.app:main`

---

## 5. Inter-Module Dependencies

```
app.py
├── config.Config
├── sink.MiracastSink
│   ├── p2p_advertiser.P2PAdvertiser
│   ├── rtsp_server.RTSPServer
│   └── media_receiver.MediaReceiver
├── service.ServiceManager
└── ui.display_window.DisplayWindow
    ├── ui.status_view.StatusView
    ├── ui.settings_view.SettingsView
    │   ├── config.Config
    │   └── service.ServiceManager
    └── ui.stream_info.StreamInfoOverlay
```

**Signal Flow:**
```
P2PAdvertiser ──connection-requested──> MiracastSink ──state-changed──> DisplayWindow
P2PAdvertiser ──ip-assigned──────────> MiracastSink ──> RTSPServer.start()
RTSPServer ──on_play callback──────> MiracastSink ──> MediaReceiver.start()
MediaReceiver ──stream-info-changed──> MiracastSink ──stream-started──> DisplayWindow
MediaReceiver ──stats-updated────────> MiracastSink ──stats-updated──> StreamInfoOverlay
RTSPServer ──on_teardown callback──> MiracastSink ──stream-stopped──> DisplayWindow
P2PAdvertiser ──peer-disconnected───> MiracastSink ──source-disconnected──> DisplayWindow
```

---

## 6. Logging

All modules use `logging.getLogger(__name__)` with the following configuration:

- **Format:** `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
- **Handlers:** FileHandler (to `~/.local/share/ubuntu-miracast-server/logs/`) + StreamHandler (stderr)
- **Default Level:** INFO (configurable via config.json general.log_level)

**Log Categories:**

| Logger Name | Content |
|-------------|---------|
| `miracast_server.sink` | State transitions, high-level events |
| `miracast_server.p2p_advertiser` | wpa_cli commands and responses, P2P events |
| `miracast_server.rtsp_server` | RTSP messages (request/response), negotiation |
| `miracast_server.media_receiver` | Pipeline state, GStreamer bus messages, stats |
| `miracast_server.config` | Config load/save operations |
| `miracast_server.service` | systemctl commands and results |

---

## 7. Error Codes

| Code | Constant | Description |
|------|----------|-------------|
| 1 | `ERR_P2P_INIT` | Failed to initialize P2P advertiser (wpa_supplicant unavailable) |
| 2 | `ERR_P2P_LISTEN` | Failed to enter P2P listen state |
| 3 | `ERR_RTSP_BIND` | Failed to bind RTSP server port |
| 4 | `ERR_PIPELINE` | GStreamer pipeline creation or state change failed |
| 5 | `ERR_DHCP` | DHCP IP assignment failed after group formation |
| 6 | `ERR_NEGOTIATION` | RTSP/WFD negotiation failed (timeout or protocol error) |
