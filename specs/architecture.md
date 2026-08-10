# Architecture & Design Specification

## Ubuntu Miracast Server (Sink) v1.0.0

**Document Version:** 1.0  
**Date:** 2026-08-10  
**Status:** Draft

---

## 1. Overview

The Ubuntu Miracast Server is a Python-based GTK 4 desktop application that acts as a Miracast sink — receiving wireless screen casts from Miracast source devices. The architecture follows a layered, modular design with clear separation between UI, core protocol logic, media handling, and system integration.

---

## 2. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      Application Layer                           │
│          app.py — MiracastServerApp (Adw.Application)           │
├─────────────────────────────────────────────────────────────────┤
│                         UI Layer                                 │
│  DisplayWindow │ StatusView │ SettingsView │ StreamInfoOverlay   │
├─────────────────────────────────────────────────────────────────┤
│                        Core Layer                                │
│  MiracastSink │ RTSPServer │ MediaReceiver │ Config             │
├─────────────────────────────────────────────────────────────────┤
│                  System Integration Layer                        │
│  P2PAdvertiser (wpa_cli) │ GStreamer │ ServiceManager (systemd) │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Design

### 3.1 Application Entry Point (`app.py`)

**Class:** `MiracastServerApp(Adw.Application)`

**Responsibilities:**
- Bootstrap the GTK/Adw application
- Instantiate core components (Config, MiracastSink, ServiceManager)
- Create the display window on activation
- Route CLI flags (`--service`, `--fullscreen`, `--name`)

**Design Decisions:**
- Uses `Adw.Application` for GNOME integration and single-instance enforcement
- MiracastSink is the central orchestrator injected into the UI
- Service mode skips GTK window creation and uses GLib.MainLoop directly

### 3.2 P2P Advertiser (`p2p_advertiser.py`)

**Class:** `P2PAdvertiser(GObject.Object)`

**Responsibilities:**
- Interface with wpa_supplicant via `wpa_cli` subprocess
- Set `wfd_subelems` to advertise as WFD sink
- Enter P2P listen state for discoverability
- Accept incoming P2P group formation (GO negotiation)
- Monitor P2P events (connection, disconnection, group formation)
- Trigger DHCP after group formation

**WFD Sub-elements (wfd_subelems):**
```
# Device Information Sub-element (ID=0x00, Length=0x0006):
# Bytes 0-1: Device Info bitmap (16 bits):
#   - Bits 0-1: Device type = 01 (Primary Sink)
#   - Bit 4: Session available = 1
#   - Bit 6: WSD (Service Discovery) supported = 1
#   - Bit 7: Preferred connectivity = 0 (P2P)
#   - Bit 8: Content Protection (HDCP) = 0 (not supported)
# Bytes 2-3: Session management control port (TCP) = 7236 (0x1C44)
# Bytes 4-5: Maximum throughput (Mbps) = 300 (0x012C)
#
# Device Info value: 0x0051 = 0000 0000 0101 0001
#   bit 0 = 1 (sink), bit 4 = 1 (session available), bit 6 = 1 (WSD)
#
# Full sub-element: 00 0006 0051 1C44 012C
#
# Coupled Sink sub-element (ID=0x07, Length=0x0001): status = 0 (not coupled)
# Full: 07 0001 00
#
# Combined wfd_subelems string for wpa_cli:
wfd_subelems = "0006 0051 1C44 012C 0700 0100"
```

**wpa_cli Commands Used:**
```bash
wpa_cli -i <interface> set wifi_display 1
wpa_cli -i <interface> wfd_subelem_set 0 000600111C44012C
wpa_cli -i <interface> wfd_subelem_set 7 0006000000000000
wpa_cli -i <interface> p2p_listen
wpa_cli -i <interface> p2p_connect <peer_addr> pbc
wpa_cli -i <interface> status
```

**Event Monitoring:**
- Runs `wpa_cli -i <interface> -a <action_script>` or polls `wpa_cli` for events
- Key events: `P2P-GO-NEG-REQUEST`, `P2P-GROUP-STARTED`, `P2P-GROUP-REMOVED`, `P2P-DEVICE-FOUND`

**DHCP Handling:**
- If sink is P2P Client: runs `dhclient <p2p_interface>` to obtain IP
- If sink is P2P GO: starts `dnsmasq` on the P2P interface to assign IP to source

### 3.3 Connection Acceptor (within P2PAdvertiser)

**Responsibilities:**
- Detect incoming `P2P-GO-NEG-REQUEST` or `P2P-PROV-DISC-PBC-REQ`
- Auto-accept or prompt user based on configuration
- Complete WPS PBC exchange
- Report peer IP address after DHCP completes

### 3.4 RTSP Server (`rtsp_server.py`)

**Class:** `RTSPServer`

**Responsibilities:**
- Listen on TCP port (default 7236) for incoming RTSP connection from source
- Parse RTSP requests (method, URI, headers, body)
- Generate RTSP responses with proper status codes and headers
- Implement WFD capability exchange (M1–M7 message flow)
- Maintain session state and timeout
- Signal when streaming should start/stop

**RTSP/WFD Message Sequence:**

```
Source (Client)                          Sink (Server)
     |                                        |
     |──── M1: OPTIONS ──────────────────────>│  (Source queries sink methods)
     │<─── 200 OK (Public: methods) ─────────│
     |                                        |
     │<─── M2: OPTIONS ──────────────────────│  (Sink queries source methods)
     |──── 200 OK (Public: methods) ─────────>│
     |                                        |
     |──── M3: GET_PARAMETER ────────────────>│  (Source queries sink capabilities)
     │     Body: wfd_video_formats            │
     │           wfd_audio_codecs             │
     │           wfd_client_rtp_ports         │
     │           wfd_content_protection       │
     │<─── 200 OK ──────────────────────────│
     │     Body: wfd_video_formats: ...       │
     │           wfd_audio_codecs: ...        │
     │           wfd_client_rtp_ports: ...    │
     │           wfd_content_protection: none │
     |                                        |
     |──── M4: SET_PARAMETER ────────────────>│  (Source sets selected params)
     │     Body: wfd_video_formats: (selected)│
     │           wfd_audio_codecs: (selected) │
     │           wfd_presentation_URL: ...    │
     │<─── 200 OK ──────────────────────────│
     |                                        |
     |──── M5: SETUP ───────────────────────>│  (Source requests transport setup)
     │     Transport: RTP/AVP/UDP;unicast;    │
     │       client_port=<port>               │
     │<─── 200 OK ──────────────────────────│
     │     Transport: ...;server_port=<port>  │
     │     Session: <session_id>;timeout=30   │
     |                                        |
     |──── M6: PLAY ────────────────────────>│  (Source starts streaming)
     │     Session: <session_id>              │
     │<─── 200 OK ──────────────────────────│
     |                                        |
     │     ═══ RTP/MPEG-TS data flows ═══     │
     |                                        |
     |──── M7: TEARDOWN ────────────────────>│  (Source ends session)
     │     Session: <session_id>              │
     │<─── 200 OK ──────────────────────────│
     |                                        |
```

**Capability Response Formats:**

```
wfd_video_formats: 00 00 02 10 0001DEFF 00000000 00000000 00 0000 0000 00 none none
# Field breakdown:
# - 00: native resolution index (CEA table, index 0 = 640x480p60)
# - 00: preferred display mode (0 = not supported)
# - 02: H.264 profile (0x02 = CHP: Constrained High Profile)
# - 10: H.264 level (0x10 = Level 4.2)
# - 0001DEFF: CEA resolution bitmap (supports 640x480p60 through 1920x1080p30)
#   Bit 0: 640x480p60, Bit 5: 1280x720p30, Bit 7: 1920x1080p30, etc.
# - 00000000: VESA resolution bitmap (none supported)
# - 00000000: HH (Handheld) resolution bitmap (none supported)
# - 00: latency (0 = no additional latency)
# - 0000: min slice size
# - 0000: slice encoding params
# - 00: frame rate control
# - none: max-hres (none = no constraint)
# - none: max-vres (none = no constraint)

wfd_audio_codecs: AAC 00000007 00
# AAC-LC codec
# 00000007 = bitmap: bit0=48kHz/16bit/2ch, bit1=44.1kHz/16bit/2ch, bit2=48kHz/16bit/4ch
# 00 = latency (none)

wfd_client_rtp_ports: RTP/AVP/UDP;unicast 1028 0 mode=play
# Transport: RTP over AVP over UDP, unicast
# Port 1028 for RTP, 0 for RTCP (disabled)
# mode=play (streaming mode)

wfd_content_protection: none
# HDCP not supported
```

### 3.5 Media Receiver (`media_receiver.py`)

**Class:** `MediaReceiver(GObject.Object)`

**Responsibilities:**
- Construct and manage GStreamer receive/decode/render pipeline
- Start/stop pipeline based on RTSP session state
- Report stream statistics (bitrate, fps, resolution)
- Handle pipeline errors and EOS

**GStreamer Receive Pipeline:**

```
┌─────────┐   ┌──────────────┐   ┌────────┐   ┌───────────┐   ┌─────────────┐   ┌──────────────┐   ┌─────────────────────┐
│ udpsrc  │──>│rtpmp2tdepay  │──>│tsdemux │──>│ h264parse │──>│ avdec_h264  │──>│ videoconvert │──>│ gtk4paintablesink   │
│port=1028│   │              │   │        │   │           │   │(or vaapidec)│   │              │   │ (or autovideosink)  │
└─────────┘   └──────────────┘   │        │   └───────────┘   └─────────────┘   └──────────────┘   └─────────────────────┘
                                  │        │
                                  │ audio  │   ┌───────────┐   ┌──────────────┐   ┌───────────────┐
                                  │  pad  ─│──>│ aacparse  │──>│  avdec_aac   │──>│ autoaudiosink │
                                  │        │   │           │   │(or fdkaacdec)│   │               │
                                  └────────┘   └───────────┘   └──────────────┘   └───────────────┘
```

**Pipeline String (video + audio):**
```python
pipeline_str = (
    f"udpsrc port={rtp_port} caps=\"application/x-rtp,media=video,clock-rate=90000,"
    f"encoding-name=MP2T\" ! rtpmp2tdepay ! tsdemux name=demux "
    f"demux. ! queue ! h264parse ! avdec_h264 ! videoconvert ! "
    f"gtk4paintablesink name=videosink "
    f"demux. ! queue ! aacparse ! avdec_aac ! audioconvert ! audioresample ! "
    f"autoaudiosink name=audiosink"
)
```

**Fallback (service/headless mode):**
```python
# Replace gtk4paintablesink with autovideosink or fakesink
pipeline_str = pipeline_str.replace("gtk4paintablesink", "autovideosink")
```

**Hardware Acceleration:**
- Attempts `vaapih264dec` first, falls back to `avdec_h264`
- Detection via `Gst.ElementFactory.find("vaapih264dec")`

### 3.6 Display Renderer (within UI — `display_window.py`)

**Class:** `DisplayWindow(Adw.ApplicationWindow)`

**Responsibilities:**
- Host the `Gtk.Picture` widget backed by `gtk4paintablesink`'s `GdkPaintable`
- Toggle fullscreen mode (F11, double-click, Escape to exit)
- Show/hide stream info overlay
- Display waiting screen when no stream active
- Show connection status in header bar

**Widget Hierarchy:**
```
DisplayWindow (Adw.ApplicationWindow)
├── Adw.HeaderBar (hidden in fullscreen)
│   ├── StatusLabel ("Advertising..." / "Connected to: Device X")
│   ├── DisconnectButton
│   └── MenuButton → Settings, Fullscreen, About, Quit
├── Gtk.Overlay
│   ├── Gtk.Stack
│   │   ├── WaitingView (page: "waiting") — spinner + "Waiting for connection..."
│   │   └── Gtk.Picture (page: "video") — bound to paintable from GStreamer
│   └── StreamInfoOverlay (top-right) — resolution, bitrate, fps
└── (nothing else — video fills the window)
```

### 3.7 Config Module (`config.py`)

**Class:** `Config`

**Storage:**
- Location: `~/.config/ubuntu-miracast-server/config.json` (XDG compliant)
- Format: Nested JSON object with sections

**Configuration Schema:**
```json
{
  "general": {
    "device_name": "",
    "auto_accept": true,
    "log_level": "INFO",
    "start_fullscreen": false
  },
  "network": {
    "rtsp_port": 7236,
    "rtp_port": 1028,
    "p2p_interface": "wlan0",
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
  }
}
```

### 3.8 Service Module (`service.py`)

**Class:** `ServiceManager`

**Service File Location:** `~/.config/systemd/user/ubuntu-miracast-server.service`

**Service File Content:**
```ini
[Unit]
Description=Ubuntu Miracast Server (Wi-Fi Display Sink)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/ubuntu-miracast-server --service
Restart=on-failure
RestartSec=5
Environment=DISPLAY=:0

[Install]
WantedBy=default.target
```

---

## 4. Threading Model

| Thread | Responsibility | Sync Mechanism |
|--------|---------------|----------------|
| Main (GTK) | UI rendering, GObject signal dispatch, user interaction | — |
| P2P Monitor | wpa_cli event polling, subprocess management | `GLib.idle_add()` for signals to main thread |
| RTSP Server | TCP socket accept + request/response handling | `GLib.idle_add()` for state change signals |
| GStreamer Pipeline | Internal GStreamer threads (decoding, rendering) | GStreamer bus messages dispatched to main thread via `bus.add_watch()` |

**Key Invariants:**
- All GObject signal emissions and GTK widget updates happen on the main thread via `GLib.idle_add()`
- The RTSP server thread handles one TCP connection at a time (single source)
- GStreamer pipeline state changes are requested from the main thread
- The P2P monitor thread is a daemon thread that exits when the application exits

**Thread Communication Flow:**
```
P2PAdvertiser Thread ──idle_add──> Main Thread ──> MiracastSink ──> RTSPServer Thread
                                       │                                    │
                                       │<────────── idle_add ──────────────│
                                       │
                                       ├──> MediaReceiver (pipeline start/stop)
                                       │         │
                                       │<── bus_watch (messages) ──────────│
                                       │
                                       └──> DisplayWindow (UI updates)
```

---

## 5. State Machine

```
                    start_advertising()
        ┌──────┐ ─────────────────────> ┌──────────────┐
        │ Idle │                         │ Advertising  │
        └──────┘ <───────────────────── └──────────────┘
                    stop_advertising()          │
                                               │ P2P-GO-NEG-REQUEST
                                               v
                                        ┌──────────────┐
                                        │ Connecting   │
                                        └──────────────┘
                                               │
                              P2P-GROUP-STARTED + DHCP complete
                                               │
                                               v
                                        ┌──────────────┐
                          M1-M7 ───────>│ Negotiating  │
                          exchange       └──────────────┘
                                               │
                                          PLAY (M6)
                                               │
                                               v
                                        ┌──────────────┐
                                        │  Streaming   │
                                        └──────────────┘
                                               │
                              TEARDOWN (M7) or source disconnect
                                               │
                                               v
                                        ┌──────────────┐
                                        │ Disconnected │──> return to Advertising
                                        └──────────────┘
```

**State Transitions:**

| From | Event | To | Action |
|------|-------|----|--------|
| Idle | `start_advertising()` | Advertising | Set wfd_subelems, enter P2P listen |
| Advertising | `stop_advertising()` | Idle | Exit P2P listen, clear wfd_subelems |
| Advertising | P2P-GO-NEG-REQUEST | Connecting | Accept negotiation, start WPS |
| Connecting | P2P-GROUP-STARTED | Negotiating | Run DHCP, start RTSP server |
| Negotiating | PLAY received (M6) | Streaming | Start GStreamer pipeline |
| Streaming | TEARDOWN received (M7) | Disconnected | Stop pipeline, close RTSP |
| Streaming | Source disconnect detected | Disconnected | Stop pipeline, cleanup |
| Disconnected | (automatic) | Advertising | Re-enter P2P listen |

---

## 6. Network Architecture

### 6.1 Connection Sequence

```
1. Sink enters P2P listen state (wpa_cli p2p_listen)
2. Source discovers sink via P2P find
3. Source initiates GO negotiation (P2P-GO-NEG-REQUEST event on sink)
4. Sink accepts (wpa_cli p2p_connect <addr> pbc)
5. Group formation completes (P2P-GROUP-STARTED)
6. New virtual interface created (e.g., p2p-wlan0-0)
7. DHCP runs on the P2P interface:
   - If sink is client: dhclient p2p-wlan0-0
   - If sink is GO: dnsmasq --interface=p2p-wlan0-0 --dhcp-range=192.168.49.10,192.168.49.50
8. Source connects to sink's RTSP port (TCP 7236) on the P2P interface IP
9. RTSP M1-M7 exchange over TCP
10. RTP/MPEG-TS media flows over UDP to sink's RTP port (1028)
```

### 6.2 Port Usage

| Port | Protocol | Direction | Purpose |
|------|----------|-----------|---------|
| 7236 | TCP | Source → Sink | RTSP control channel |
| 1028 | UDP | Source → Sink | RTP media data (MPEG-TS) |

---

## 7. File System Layout

```
ubuntu-miracast-server/
├── src/
│   └── miracast_server/
│       ├── __init__.py
│       ├── app.py                    # Application entry point
│       ├── sink.py                   # MiracastSink orchestrator
│       ├── p2p_advertiser.py         # Wi-Fi Direct P2P advertisement
│       ├── rtsp_server.py            # RTSP/WFD protocol server
│       ├── media_receiver.py         # GStreamer receive pipeline
│       ├── config.py                 # Configuration management
│       ├── service.py                # Systemd service management
│       └── ui/
│           ├── __init__.py
│           ├── display_window.py     # Main display window
│           ├── status_view.py        # Connection status widget
│           ├── settings_view.py      # Settings page
│           └── stream_info.py        # Stream info overlay
├── tests/
│   ├── __init__.py
│   ├── test_rtsp_server.py
│   ├── test_p2p_advertiser.py
│   ├── test_media_receiver.py
│   ├── test_sink.py
│   ├── test_config.py
│   ├── test_service.py
│   └── test_integration.py
├── data/
│   ├── ubuntu-miracast-server.desktop
│   └── ubuntu-miracast-server.svg
├── debian/
│   ├── control
│   ├── changelog
│   ├── rules
│   ├── copyright
│   └── ubuntu-miracast-server.install
├── scripts/
│   ├── build.sh
│   ├── test.sh
│   └── release.sh
├── specs/
│   ├── requirements.md
│   ├── architecture.md
│   ├── api.md
│   └── testing.md
├── docs/
│   └── README.md
├── setup.py
├── setup.cfg
├── pyproject.toml
├── Makefile
├── VERSION
├── LICENSE
├── README.md
├── CHANGELOG.md
└── .gitignore
```

**Runtime Data Paths:**
```
~/.config/ubuntu-miracast-server/
├── config.json                              # Application settings

~/.config/systemd/user/
└── ubuntu-miracast-server.service           # Systemd service file (generated)

~/.local/share/ubuntu-miracast-server/
└── logs/
    ├── miracast-server.log                  # Application log
    └── miracast-service.log                 # Service mode log
```

---

## 8. Error Handling Strategy

| Layer | Strategy |
|-------|----------|
| P2P Advertiser | Errors caught in monitor thread, emitted as signal, logged; retry P2P listen on failure |
| RTSP Server | Malformed requests get 400 response; socket errors close connection and signal disconnect |
| Media Receiver | GStreamer bus ERROR messages stop pipeline, emit error signal; WARNING messages logged |
| Config | Load failure falls back to defaults; save failure logged with warning |
| Display Window | Errors shown via `Adw.MessageDialog`; fullscreen errors handled gracefully |
| Service | systemd `Restart=on-failure` with 5s delay |

---

## 9. Technology Rationale

| Choice | Rationale |
|--------|-----------|
| Python 3.12 | Consistency with client project, good GTK/GStreamer bindings |
| GTK 4 + libadwaita | Native GNOME look, `gtk4paintablesink` for zero-copy video display |
| GStreamer | Industry-standard, handles RTP/MPEG-TS/H.264/AAC decode pipeline |
| Custom RTSP server | WFD-specific message flow not supported by generic RTSP libraries |
| wpa_cli subprocess | Same approach as client; avoids complex D-Bus wpa_supplicant API |
| GObject signals | Native GTK event loop integration, type-safe inter-component communication |
| JSON config | Simple, human-readable, consistent with client project |
| Systemd user service | Standard Linux service management, suitable for always-on sink |
