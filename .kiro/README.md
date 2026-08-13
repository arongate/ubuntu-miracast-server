# Agent Configuration — Ubuntu Miracast Server

This directory contains context and instructions for AI coding agents working on this project.

## Project Identity

- **Name:** Ubuntu Miracast Server
- **Type:** Python GTK 4 desktop application + systemd service
- **Purpose:** Miracast sink (Wi-Fi Display receiver) for Ubuntu
- **Language:** Python 3.10+ (targeting 3.12)
- **UI Framework:** GTK 4 + libadwaita (via PyGObject)
- **Media:** GStreamer 1.20+ (pipeline-based)
- **Networking:** wpa_supplicant (via wpa_cli subprocess), TCP/UDP sockets

## Quick Orientation

| Path | Purpose |
|------|---------|
| `src/miracast_server/` | Main application source |
| `src/miracast_server/ui/` | GTK UI views |
| `tests/` | pytest test suite |
| `specs/` | Design specifications (requirements, architecture, API, testing) |
| `docs/` | User documentation |
| `debian/` | Debian packaging |

## How to Build & Test

```bash
# Setup (one-time)
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run the application
ubuntu-miracast-server
```

## Key Design Decisions

1. GObject signals for component communication (all via `GLib.idle_add()` from threads)
2. Single active connection invariant — only one source at a time
3. Security-first: wpa_cli params validated, no `shell=True`, RTSP input size-limited
4. Atomic file writes with 0600 permissions for config/history
5. Hardware decode fallback chain: vaapi → nvdec → avdec_h264
