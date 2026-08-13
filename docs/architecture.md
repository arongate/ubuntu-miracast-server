# Architecture

This document describes the internal architecture of Ubuntu Miracast Server — module responsibilities, signal flow, threading model, and component interactions.

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      Application Layer                           │
│           app.py — MiracastServerApp (Adw.Application)          │
├─────────────────────────────────────────────────────────────────┤
│                         UI Layer                                 │
│   MainWindow │ DisplayView │ SessionsView │ SettingsView        │
├─────────────────────────────────────────────────────────────────┤
│                        Core Layer                                │
│  MiracastAdvertiser │ ConnectionHandler │ MiracastReceiver       │
│  RTSPParser │ PipelineBuilder │ ServerConfig │ SessionHistory    │
├─────────────────────────────────────────────────────────────────┤
│                  System Integration Layer                        │
│  wpa_cli (P2P) │ GStreamer │ systemd │ DHCP (dhclient/dnsmasq) │
└─────────────────────────────────────────────────────────────────┘
```

## Module Responsibilities

### `app.py` — Application Entry Point

- Parses CLI arguments (`--service`, `--fullscreen`, `--name`)
- Bootstraps GTK/Adw application or headless GLib main loop
- Instantiates all core components
- Wires GObject signals between components
- Manages graceful shutdown (SIGTERM/SIGINT)

### `advertiser.py` — WFD Sink Advertisement

- Interfaces with wpa_supplicant via `wpa_cli`
- Sets WFD sub-elements (Device Info, Associated BSSID, Coupled Sink)
- Enters P2P listen state for discoverability
- Emits: `advertising-started`, `advertising-stopped`, `advertising-error`

### `connection.py` — Wi-Fi Direct Connection Handler

- Spawns a daemon thread monitoring wpa_cli events
- Handles `P2P-GO-NEG-REQUEST`, `P2P-GROUP-STARTED`, `P2P-GROUP-REMOVED`
- Performs DHCP after group formation (dhclient as client, dnsmasq as GO)
- Enforces single-connection invariant
- Emits: `connection-received`, `connection-lost`, `connection-error`

### `rtsp.py` — RTSP Protocol Layer

- Stateless parser/builder for RTSP messages
- WFD parameter parsing and capability response generation
- Request size validation (security: 8KB header, 64KB body limits)
- Completely isolated from I/O — pure data transformation

### `receiver.py` — Stream Reception

- Manages RTSP TCP session (negotiation flow M1–M7)
- Constructs GStreamer pipeline via `PipelineBuilder`
- Monitors stream health (RTP timeout, frame drops, bitrate)
- Hardware decode fallback (VAAPI → software on failure)
- Emits: `stream-started`, `stream-stopped`, `stream-error`, `stats-updated`

### `config.py` — Configuration Management

- JSON persistence at `~/.config/ubuntu-miracast-server/config.json`
- Validation rules for constrained values (ports, timeouts, intents)
- Atomic writes with 0600 permissions
- Graceful handling of malformed files

### `history.py` — Session History

- JSON persistence at `~/.local/share/ubuntu-miracast-server/history.json`
- 500-record cap (oldest discarded on overflow)
- Sorted retrieval (most recent first)
- Atomic writes with 0600 permissions

### `service.py` — Service Mode

- Generates and installs systemd user service file
- Headless operation with GLib main loop (no GTK)
- Idle timeout for automatic shutdown
- Rollback-safe service installation

### `utils.py` — Security Utilities

- wpa_cli parameter allowlist validation (alphanumeric + `:_-` only)
- Codec whitelist (`H264`, `AAC`)
- RTSP size limit constants
- Port validation helper

## Signal Flow

The application is event-driven using GObject signals. All signals are emitted on the GTK main thread via `GLib.idle_add()`.

```
┌──────────────┐         ┌───────────────────┐         ┌─────────────────┐
│  Advertiser  │────────>│ ConnectionHandler  │────────>│ MiracastReceiver│
│              │ started  │                   │ received │                 │
└──────────────┘         └───────────────────┘         └─────────────────┘
       │                          │                           │
       │                          │                           │ stream-stopped
       │                          │                           │ stream-error
       │                          │                           ▼
       │                          │                    ┌──────────────┐
       │                          │                    │   History    │
       │                          │                    │ add_session()│
       │                          │                    └──────────────┘
       │                          │                           │
       ◄──────────────────────────┼───────────────────────────┘
       │            return to advertising                      
```

### Complete Signal Chain

1. `Advertiser.advertising-started` → ConnectionHandler starts listening
2. `ConnectionHandler.connection-received` → Receiver starts RTSP session
3. `Receiver.stream-started` → UI transitions to receiving state
4. `Receiver.stats-updated` → UI updates stats overlay
5. `Receiver.stream-stopped` → History records session → returns to advertising
6. `Receiver.stream-error` → History records partial session → returns to advertising
7. `ConnectionHandler.connection-lost` → UI returns to idle state

## Threading Model

| Thread | Responsibility | Communication |
|--------|---------------|---------------|
| **Main (GTK)** | UI rendering, GObject signal dispatch, user interaction | — |
| **P2P Monitor** | wpa_cli event polling via subprocess | `GLib.idle_add()` for signals |
| **RTSP Session** | TCP socket handling, RTSP message exchange | `GLib.idle_add()` for signals |
| **Stats Monitor** | 1-second pipeline stat queries, stream loss detection | `GLib.idle_add()` for signals |
| **GStreamer** | Internal decoding/rendering threads | Bus messages → main thread via `bus.add_watch()` |

**Thread safety rules:**
- All GObject signal emissions go through `GLib.idle_add()` to dispatch on the main thread
- Core state is protected by `threading.Lock` where accessed from multiple threads
- The `_running` flag is set before joining threads; joins have 5-second timeouts

## GStreamer Pipeline

```
┌─────────┐   ┌──────────────┐   ┌────────┐   ┌───────────┐   ┌─────────────┐   ┌──────────────┐   ┌─────────────────────┐
│ udpsrc  │──>│rtpmp2tdepay  │──>│tsdemux │──>│ h264parse │──>│  decoder    │──>│ videoconvert │──>│   video sink        │
│(2MB buf)│   │              │   │        │   │           │   │(vaapi/sw)   │   │              │   │(gtk4paint/fakesink) │
└─────────┘   └──────────────┘   │        │   └───────────┘   └─────────────┘   └──────────────┘   └─────────────────────┘
                                  │ audio  │
                                  │  pad   │──>┌─────────┐──>┌──────────┐──>┌─────────────┐──>┌───────────┐
                                  └────────┘   │aacparse │   │avdec_aac │   │audioconvert │   │pulsesink  │
                                               └─────────┘   └──────────┘   └─────────────┘   └───────────┘
```

**Queue configuration:** max-size-buffers=200, max-size-bytes=10MB, max-size-time=1s

**Decoder selection:** vaapidecodebin → nvh264dec → avdec_h264 (first available)

## Security Model

- **wpa_cli parameters** are validated against an allowlist before subprocess execution
- **Subprocess calls** always use list format (never `shell=True`)
- **RTSP input** is size-limited (8KB headers, 64KB body) before parsing
- **Codec names** are checked against a whitelist before pipeline construction
- **Config/history files** use 0600 permissions (user-only read/write)
- **RTSP connections** are validated against the expected P2P peer address
- **Port numbers** are validated (1024–65535) before binding

## Graceful Shutdown

Shutdown is triggered by SIGTERM, SIGINT, or window close. The sequence is:

1. **Stop Receiver** — pipeline → NULL, close sockets, join threads (5s timeout)
2. **Stop ConnectionHandler** — disconnect peer, stop event monitor thread
3. **Stop Advertiser** — p2p_stop_find

Each step logs failures but continues the sequence. Partial session stats are recorded to history on error-path shutdowns.

## Known Hardware Constraints

### Single-Radio Concurrent Channel Limitation

Most laptop Wi-Fi adapters (Intel AX200/AX201/AX210, etc.) have a single radio that cannot operate on two different frequencies simultaneously. Since the regular Wi-Fi connection (to a router) and the P2P Miracast connection often negotiate different channels:

- The P2P group formation **succeeds at the protocol level** (WPS exchange completes)
- But the **driver fails** to maintain both connections, causing an immediate disconnection
- The `P2P-GROUP-FORMATION-SUCCESS` event fires, followed by `CTRL-EVENT-EAP-FAILURE`

**Workaround:** Disconnect from the regular Wi-Fi network before accepting Miracast connections, use Ethernet for internet, or use a dedicated secondary USB Wi-Fi adapter for P2P.

This constraint is documented in the Getting Started guide's troubleshooting section.
