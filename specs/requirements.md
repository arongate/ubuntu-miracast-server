# Requirements Specification

## Ubuntu Miracast Server (Sink) v1.0.0

**Document Version:** 1.0  
**Date:** 2026-08-10  
**Status:** Draft

---

## 1. Introduction

### 1.1 Purpose

This document specifies the functional and non-functional requirements for the Ubuntu Miracast Server application — a Miracast sink (Wi-Fi Display receiver) for Ubuntu 24.04 LTS that accepts incoming screen casting sessions from Miracast source devices.

### 1.2 Scope

The application advertises as a Wi-Fi Display sink via Wi-Fi Direct P2P, handles the full Miracast/WFD RTSP negotiation protocol (M1–M7), receives RTP/MPEG-TS streams containing H.264 video and AAC audio, decodes them, and renders the received content in a GTK 4 window.

### 1.3 Relationship to Ubuntu Miracast Client

This is the companion receiver to the existing `ubuntu-miracast-client` (source/sender). Both projects share conventions: Python 3.12, GTK 4 + libadwaita, wpa_supplicant via wpa_cli, GStreamer, systemd user service, JSON config at XDG paths.

### 1.4 Target Platform

- Ubuntu 24.04 LTS
- Python 3.10+ (recommended 3.12)
- GNOME desktop environment (primary), other GTK-compatible desktops (secondary)

---

## 2. Functional Requirements

### 2.1 P2P Advertisement

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-PA01 | The system SHALL advertise as a Wi-Fi Display (WFD) sink device via Wi-Fi Direct P2P using wpa_supplicant | Must |
| FR-PA02 | The system SHALL set `wfd_subelems` in wpa_supplicant to advertise WFD Device Information, Associated BSSID, and Coupled Sink Information sub-elements | Must |
| FR-PA03 | The WFD Device Information sub-element SHALL indicate: WFD Sink, session available, WFD Service Discovery supported, preferred connectivity = P2P, CP not supported, RTSP port (default 7236) | Must |
| FR-PA04 | The system SHALL set the device name advertised via P2P to a configurable friendly name (default: hostname) | Must |
| FR-PA05 | The system SHALL support starting and stopping advertisement on demand | Must |
| FR-PA06 | The system SHALL remain discoverable (P2P listen state) while advertising | Must |
| FR-PA07 | The system SHALL support configuring the P2P listen channel (default: auto) | Should |
| FR-PA08 | The system SHALL support both 2.4 GHz and 5 GHz operation channels | Should |

### 2.2 Connection Handling

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-CH01 | The system SHALL accept incoming P2P group formation requests from Miracast sources | Must |
| FR-CH02 | The system SHALL handle WPS PBC (Push Button Configuration) for connection authentication | Must |
| FR-CH03 | The system SHALL act as P2P Group Client (let source be Group Owner) or negotiate GO role as needed | Must |
| FR-CH04 | The system SHALL handle DHCP IP address assignment after P2P group formation (obtain IP as client or run minimal DHCP server as GO) | Must |
| FR-CH05 | The system SHALL detect source disconnection and clean up resources | Must |
| FR-CH06 | The system SHALL support only one active connection at a time | Must |
| FR-CH07 | The system SHALL emit events for connection state changes (connecting, connected, disconnected) | Must |
| FR-CH08 | The system SHALL support WPS PIN method as an alternative to PBC | Could |

### 2.3 RTSP/WFD Negotiation

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-RN01 | The system SHALL implement an RTSP server listening on a configurable TCP port (default: 7236) | Must |
| FR-RN02 | The system SHALL handle M1 (OPTIONS from source) and respond with supported RTSP methods: `org.wfa.wfd1.0, GET_PARAMETER, SET_PARAMETER, SETUP, PLAY, TEARDOWN` | Must |
| FR-RN03 | The system SHALL send M2 (OPTIONS to source) to query the source's supported methods | Must |
| FR-RN04 | The system SHALL handle M3 (GET_PARAMETER from source) and respond with sink capabilities including: `wfd_video_formats`, `wfd_audio_codecs`, `wfd_client_rtp_ports`, `wfd_content_protection`, `wfd_coupled_sink` | Must |
| FR-RN05 | The `wfd_video_formats` response SHALL advertise supported H.264 profiles (CBP, CHP), levels, resolutions (CEA, VESA, HH tables), and frame rates | Must |
| FR-RN06 | The `wfd_audio_codecs` response SHALL advertise supported AAC-LC codec with sampling rates (44.1 kHz, 48 kHz) and channel configurations (stereo) | Must |
| FR-RN07 | The `wfd_client_rtp_ports` response SHALL specify the UDP port for RTP reception and transport profile (RTP/AVP/UDP;unicast) | Must |
| FR-RN08 | The system SHALL handle M4 (SET_PARAMETER from source) containing the selected video format, audio codec, and presentation URL | Must |
| FR-RN09 | The system SHALL handle M5 (SETUP from source) with Transport header and respond with a session ID and server port confirmation | Must |
| FR-RN10 | The system SHALL handle M6 (PLAY from source) and begin accepting RTP media data | Must |
| FR-RN11 | The system SHALL handle M7 (TEARDOWN from source) and stop the media pipeline | Must |
| FR-RN12 | The system SHALL validate RTSP CSeq headers and maintain sequence numbering | Must |
| FR-RN13 | The system SHALL handle RTSP keep-alive via GET_PARAMETER with empty body | Must |
| FR-RN14 | The system SHALL respond with appropriate RTSP error codes (400, 404, 455, 500) for malformed requests | Must |
| FR-RN15 | The system SHALL support RTSP session timeout (default: 30 seconds) | Should |
| FR-RN16 | The system SHALL send M8 (PAUSE) request to source when user pauses playback | Could |

### 2.4 Media Reception & Playback

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-MR01 | The system SHALL receive RTP/MPEG-TS packets on the negotiated UDP port | Must |
| FR-MR02 | The system SHALL demultiplex MPEG-TS to extract H.264 video elementary stream | Must |
| FR-MR03 | The system SHALL decode H.264 video (Constrained Baseline Profile and Constrained High Profile) | Must |
| FR-MR04 | The system SHALL render decoded video frames in real-time | Must |
| FR-MR05 | The system SHALL demultiplex MPEG-TS to extract AAC audio elementary stream | Must |
| FR-MR06 | The system SHALL decode AAC-LC audio and output to system audio device | Must |
| FR-MR07 | The system SHALL maintain audio/video synchronization using MPEG-TS PTS timestamps | Must |
| FR-MR08 | The system SHALL handle stream resolution changes dynamically (format renegotiation) | Should |
| FR-MR09 | The system SHALL support hardware-accelerated H.264 decoding (VA-API) when available | Should |
| FR-MR10 | The system SHALL handle packet loss gracefully without crashing | Must |
| FR-MR11 | The system SHALL report stream statistics (bitrate, frame rate, resolution, packet loss) | Should |
| FR-MR12 | The system SHALL support muting/unmuting received audio | Should |
| FR-MR13 | The system SHALL support volume control for received audio | Could |

### 2.5 User Interface

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-UI01 | The system SHALL provide a GTK 4 / libadwaita interface | Must |
| FR-UI02 | The system SHALL display connection status (Idle, Advertising, Connecting, Streaming, Disconnected) | Must |
| FR-UI03 | The system SHALL display the received video stream in an embedded GTK widget | Must |
| FR-UI04 | The system SHALL support fullscreen mode for video display (toggle with F11 or double-click) | Must |
| FR-UI05 | The system SHALL display stream information overlay (resolution, bitrate, source device name) | Should |
| FR-UI06 | The system SHALL show the connected source device name and address | Must |
| FR-UI07 | The system SHALL provide a "Disconnect" button to terminate the active session | Must |
| FR-UI08 | The system SHALL provide a settings page for configuration | Must |
| FR-UI09 | The system SHALL show a waiting/advertisement screen when no source is connected | Must |
| FR-UI10 | The system SHALL provide a header bar with menu (Settings, About, Quit) | Should |
| FR-UI11 | The system SHALL support `--fullscreen` CLI flag to start in fullscreen mode | Should |
| FR-UI12 | The system SHALL hide cursor during fullscreen video playback | Could |

### 2.6 Configuration

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-CF01 | The system SHALL persist configuration in JSON format at `~/.config/ubuntu-miracast-server/config.json` | Must |
| FR-CF02 | The system SHALL create default configuration if none exists | Must |
| FR-CF03 | The system SHALL support sections: general, network, display, advanced | Must |
| FR-CF04 | The system SHALL provide get/set interface for configuration values | Must |
| FR-CF05 | The system SHALL support configurable device name (advertised to sources) | Must |
| FR-CF06 | The system SHALL support configurable RTSP port (default: 7236) | Must |
| FR-CF07 | The system SHALL support configurable RTP port (default: 1028) | Must |
| FR-CF08 | The system SHALL support configurable log level (DEBUG, INFO, WARNING, ERROR) | Should |
| FR-CF09 | The system SHALL support auto-accept connections option (vs. prompt user) | Should |
| FR-CF10 | The system SHALL support configurable preferred resolution (up to 1920x1080) | Should |

### 2.7 Service Mode

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-SV01 | The system SHALL support running as a systemd user service for always-on sink mode | Must |
| FR-SV02 | The system SHALL provide enable/disable/start/stop service controls | Must |
| FR-SV03 | The system SHALL auto-generate the systemd service file | Must |
| FR-SV04 | The system SHALL check service status (enabled/running) | Must |
| FR-SV05 | The system SHALL support `--service` CLI flag to run in headless service mode (no GTK window, use autovideosink or virtual sink) | Must |
| FR-SV06 | The system SHALL automatically start advertising when launched in service mode | Must |
| FR-SV07 | The system SHALL support `--name` CLI flag to override the advertised device name | Should |
| FR-SV08 | The system SHALL restart automatically on failure (systemd Restart=on-failure) | Should |

---

## 3. Non-Functional Requirements

### 3.1 Performance

| ID | Requirement | Priority |
|----|-------------|----------|
| NFR-P01 | End-to-end latency from source capture to sink display SHALL be below 200ms under normal conditions | Must |
| NFR-P02 | The GStreamer pipeline SHALL achieve decode and render within 50ms of packet reception | Must |
| NFR-P03 | The UI SHALL remain responsive during streaming (no main thread blocking) | Must |
| NFR-P04 | The system SHALL handle 1080p30 streams (up to ~20 Mbps) without frame drops on supported hardware | Should |
| NFR-P05 | The RTSP negotiation (M1–M7) SHALL complete within 5 seconds | Should |
| NFR-P06 | Video display SHALL begin within 2 seconds of PLAY command | Should |

### 3.2 Reliability

| ID | Requirement | Priority |
|----|-------------|----------|
| NFR-R01 | The system SHALL handle source disconnection gracefully without crashing | Must |
| NFR-R02 | The system SHALL recover from transient network errors (packet loss, jitter) | Must |
| NFR-R03 | The system SHALL return to advertising state after session termination | Must |
| NFR-R04 | The system SHALL handle malformed RTSP messages without crashing | Must |
| NFR-R05 | The system SHALL log errors with full context for debugging | Must |
| NFR-R06 | The service mode SHALL restart on failure (RestartSec=5s) | Should |
| NFR-R07 | The system SHALL handle multiple sequential connections (source disconnects, new source connects) | Must |

### 3.3 Security

| ID | Requirement | Priority |
|----|-------------|----------|
| NFR-S01 | Wi-Fi Direct connections SHALL use WPA2 security | Must |
| NFR-S02 | The system SHALL NOT implement HDCP content protection (out of scope) | Must |
| NFR-S03 | Configuration files SHALL be stored with user-only read/write permissions (0600) | Should |
| NFR-S04 | The RTSP server SHALL only accept connections from the P2P peer address | Should |
| NFR-S05 | The system SHALL validate all RTSP input before processing (buffer overflow prevention) | Must |

### 3.4 Usability

| ID | Requirement | Priority |
|----|-------------|----------|
| NFR-U01 | The application SHALL follow GNOME Human Interface Guidelines | Should |
| NFR-U02 | The UI SHALL provide clear visual feedback for connection state | Must |
| NFR-U03 | Fullscreen mode SHALL be easily exitable (Escape or F11) | Must |
| NFR-U04 | The application SHALL work out-of-the-box with minimal configuration | Must |
| NFR-U05 | Error messages SHALL be user-friendly and actionable | Must |

### 3.5 Maintainability

| ID | Requirement | Priority |
|----|-------------|----------|
| NFR-M01 | The codebase SHALL follow modular architecture with clear separation of concerns | Must |
| NFR-M02 | The code SHALL be formatted with Black (line-length=100) and isort | Should |
| NFR-M03 | The code SHALL pass flake8 linting | Should |
| NFR-M04 | Test coverage SHALL be maintained with pytest (≥80% overall) | Must |
| NFR-M05 | The RTSP protocol implementation SHALL be isolated for independent testing | Must |

### 3.6 Portability

| ID | Requirement | Priority |
|----|-------------|----------|
| NFR-PT01 | The application SHALL be installable via Debian package (.deb) | Must |
| NFR-PT02 | The application SHALL be installable via pip (Python package) | Must |
| NFR-PT03 | The application SHALL support Python 3.10, 3.11, and 3.12 | Must |

---

## 4. Constraints

| ID | Constraint |
|----|-----------|
| C01 | Target platform is Ubuntu 24.04 LTS only |
| C02 | Requires Wi-Fi adapter with P2P (Wi-Fi Direct) support |
| C03 | Depends on system-level wpa_supplicant for Wi-Fi Direct P2P |
| C04 | Requires GStreamer runtime with good/bad/ugly plugins for H.264 and AAC |
| C05 | GTK 4 and libadwaita must be available on the system |
| C06 | HDCP content protection is NOT supported (no protected content playback) |
| C07 | Only one active source connection at a time |
| C08 | The sink cannot initiate connections — it waits for sources to connect |
| C09 | RTSP port 7236 is the WFD standard default; firewall rules may be needed |

---

## 5. Dependencies

### 5.1 Runtime Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| PyGObject | >=3.42.0 | GTK 4 / GLib / GStreamer Python bindings |
| pycairo | >=1.20.0 | Cairo rendering support |
| GTK 4 | System (>=4.6) | UI framework |
| libadwaita | System (>=1.2) | GNOME design patterns |
| GStreamer | System (>=1.20) | Media pipeline (decode, render, audio) |
| gst-plugins-good | System | rtpmp2tdepay, udpsrc, autoaudiosink |
| gst-plugins-bad | System | tsdemux |
| gst-plugins-ugly | System | (fallback decoders) |
| gstreamer-vaapi | System | Hardware-accelerated H.264 decoding (optional) |
| wpa_supplicant | System (>=2.10) | Wi-Fi Direct P2P advertisement and connection |
| dhclient / dhcpcd | System | DHCP client for IP assignment after group formation |
| dnsmasq | System (optional) | Lightweight DHCP server when sink is P2P GO |

### 5.2 Development Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| pytest | >=7.0.0 | Test framework |
| pytest-cov | >=4.0.0 | Coverage reporting |
| pytest-asyncio | >=0.21.0 | Async test support (RTSP server tests) |
| black | >=23.0.0 | Code formatting |
| isort | >=5.12.0 | Import sorting |
| flake8 | >=6.0.0 | Linting |
| mypy | >=1.0.0 | Type checking |

---

## 6. Future Enhancements (Out of Scope for v1.0)

| Enhancement | Description |
|-------------|-------------|
| UIBC (User Input Back Channel) | Allow sink to send input events (touch, mouse, keyboard) back to source |
| HDCP 2.x | Content protection for DRM-protected content |
| Multi-source support | Accept multiple simultaneous source connections (picture-in-picture) |
| Audio-only mode | Receive only audio stream (Miracast audio extension) |
| Source quality feedback | IDR frame requests and bitrate adaptation signaling |
| mDNS/DNS-SD advertisement | Alternative discovery mechanism alongside Wi-Fi Direct |
| Screen recording | Record received stream to file |
| Remote PIN display | Show WPS PIN on screen for PIN-based authentication |
