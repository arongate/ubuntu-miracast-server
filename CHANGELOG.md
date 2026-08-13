# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-08-10

### Added

- Initial release of Ubuntu Miracast Server
- WFD sink advertisement via Wi-Fi Direct P2P (wpa_supplicant)
- Full RTSP/WFD negotiation protocol (M1–M7 message flow)
- GStreamer receive pipeline with H.264 video and AAC audio decoding
- Hardware-accelerated decoding support (VA-API, NVDEC) with software fallback
- GTK 4 / libadwaita user interface with three views:
  - Display view with idle/connected/receiving states
  - Session history browser
  - Settings page with validation
- Fullscreen video display (F11, double-click, Escape to exit)
- Floating overlay controls in fullscreen mode
- Stream statistics overlay (resolution, bitrate, duration)
- Session history persistence (JSON, max 500 records)
- Configuration management with validation (JSON at XDG paths)
- Headless systemd user service mode (`--service` flag)
- Idle timeout for service mode auto-shutdown
- Automatic DHCP handling after P2P group formation
- Single-connection invariant (rejects new connections while streaming)
- Stream health monitoring (RTP timeout, frame drop detection, peak bitrate tracking)
- Graceful shutdown with orderly resource cleanup
- Security: wpa_cli parameter validation, RTSP size limits, codec whitelist
- `--fullscreen` and `--name` CLI options
- Debian packaging files
- Comprehensive documentation

[Unreleased]: https://github.com/yourusername/ubuntu-miracast-server/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/yourusername/ubuntu-miracast-server/releases/tag/v0.1.0
