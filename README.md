# Ubuntu Miracast Server

[![CI](https://github.com/arongate/ubuntu-miracast-server/actions/workflows/ci.yml/badge.svg)](https://github.com/arongate/ubuntu-miracast-server/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/arongate/ubuntu-miracast-server?include_prereleases)](https://github.com/arongate/ubuntu-miracast-server/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

A Wi-Fi Display (Miracast) sink for Ubuntu — receive wireless screen casts from any Miracast source device.

## ⚠️ Unstable Phase (0.x)

This project is in its initial development phase (`0.x.y`). Per [SemVer §4](https://semver.org/#spec-item-4), the public API is not yet stable — any release may introduce breaking changes. Pin your dependency to an exact version if you rely on this package.

## Features

- **Receive Miracast streams** — accept screen casts from phones, tablets, laptops, and other Miracast sources
- **Automatic discovery** — advertises as a WFD sink via Wi-Fi Direct P2P, discoverable by any Miracast source
- **Hardware-accelerated decoding** — uses VA-API or NVDEC when available, falls back to software (avdec_h264)
- **Audio support** — decodes AAC audio alongside H.264 video
- **Fullscreen display** — auto-fullscreen on stream start, toggle with F11/double-click, exit with Escape
- **Session history** — tracks past streaming sessions with stats (duration, resolution, bitrate, data)
- **Headless service mode** — run as a systemd user service for always-on reception without a GUI
- **Modern UI** — GTK 4 + libadwaita interface following GNOME HIG
- **Configurable** — device name, ports, auto-accept, resolution preferences, and more

## Screenshots

<!-- TODO: Add screenshots -->
*Screenshots coming soon.*

## Quick Start

```bash
# Install system dependencies
sudo apt install python3-gi python3-gst-1.0 \
    gir1.2-gtk-4.0 gir1.2-adw-1 \
    gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
    gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
    wpasupplicant dnsmasq

# Install uv (fast Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
git clone https://github.com/arongate/ubuntu-miracast-server.git
cd ubuntu-miracast-server
uv venv --system-site-packages
source .venv/bin/activate
uv pip install -e .

# Run
ubuntu-miracast-server
```

Your machine will appear as "Ubuntu Miracast Server" in the Miracast/wireless display list on source devices. A PIN will be displayed on screen — enter it on your phone/laptop to connect and start casting.

## Prerequisites

- **Ubuntu 24.04 LTS** (or compatible Linux distribution with GTK 4, GStreamer 1.20+)
- **Python 3.10+** (3.12 recommended)
- **Wi-Fi adapter with P2P (Wi-Fi Direct) support**
- **wpa_supplicant** running with P2P enabled

> **Note:** Not all Wi-Fi adapters support P2P mode. Intel Wi-Fi 6 (AX200/AX201) and Qualcomm Atheros adapters are known to work. Check with `iw phy | grep P2P`.

> **Important: Single-radio limitation.** Most laptop Wi-Fi adapters cannot simultaneously maintain a regular Wi-Fi connection (to your router) and a P2P connection (for Miracast). If you have a **secondary USB Wi-Fi adapter** (e.g., TP-Link AXE5400), the app will automatically use it for P2P while your built-in adapter stays connected to the internet — no configuration needed. Without a second adapter, you may need to disconnect from Wi-Fi to cast. See [Troubleshooting](docs/getting-started.md#single-radio-wi-fi-limitation-concurrent-connection-failure) for details.

### System Dependencies

```bash
sudo apt install \
    python3-gi python3-gst-1.0 \
    gir1.2-gtk-4.0 gir1.2-adw-1 \
    gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
    gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
    wpasupplicant dnsmasq

# Optional: hardware-accelerated video decoding
sudo apt install gstreamer1.0-vaapi
```

## Installation

### From Source (recommended for development)

```bash
git clone https://github.com/arongate/ubuntu-miracast-server.git
cd ubuntu-miracast-server

# Create virtual environment with system site-packages (required for GTK/GStreamer)
uv venv --system-site-packages
source .venv/bin/activate

# Install in development mode
uv pip install -e ".[dev]"
```

### From Debian Package

Download the `.deb` from the [latest release](https://github.com/arongate/ubuntu-miracast-server/releases):

```bash
sudo apt install ./ubuntu-miracast-server_*.deb
```

### From PyPI (when published)

```bash
pip install ubuntu-miracast-server
```

> **Important:** PyGObject and GStreamer bindings require system libraries. Install the system dependencies listed above before using pip.

## Usage

### GUI Mode (default)

```bash
ubuntu-miracast-server
```

The application will:
1. Start advertising as a Miracast sink on your Wi-Fi Direct interface
2. Display a WPS PIN — enter it on your source device to connect
3. Once connected, negotiate the stream and display the received video

### CLI Options

```
ubuntu-miracast-server [OPTIONS]

Options:
  --service           Run in headless service mode (no GUI, uses fakesink)
  --fullscreen        Start the window in fullscreen mode
  --name NAME         Override the advertised device name
  --interface IFACE   Override the P2P Wi-Fi interface (auto-detected if omitted)
  --help              Show help message
```

### Service Mode

Run as a background service without a GUI:

```bash
ubuntu-miracast-server --service --name "Living Room Display"
```

Or install as a systemd user service:

```bash
# The application can manage its own service file
# See docs/service-mode.md for details
systemctl --user enable ubuntu-miracast-server
systemctl --user start ubuntu-miracast-server
```

## Configuration

Configuration is stored at `~/.config/ubuntu-miracast-server/config.json` and is created automatically on first run.

Key options:

| Section | Key | Default | Description |
|---------|-----|---------|-------------|
| general | device_name | "Ubuntu Miracast Server" | Advertised device name |
| general | fullscreen_on_stream | true | Auto-fullscreen when stream starts |
| streaming | rtsp_port | 7236 | RTSP port on source (standard WFD port) |
| network | rtp_port | 1028 | Local UDP port for RTP media reception |
| network | go_intent | 15 | P2P Group Owner intent (0-15) |
| network | auto_accept | true | Auto-accept incoming connections |
| network | p2p_interface | "" | P2P interface override (auto-detected if empty) |
| service | idle_timeout | 0 | Exit service after N seconds idle (0=disabled) |

See [docs/configuration.md](docs/configuration.md) for the full reference.

## Documentation

- [Getting Started](docs/getting-started.md) — detailed setup and first-run guide
- [Architecture](docs/architecture.md) — module design, signal flow, threading model
- [Configuration](docs/configuration.md) — all options with descriptions and validation rules
- [Service Mode](docs/service-mode.md) — headless operation and systemd integration

## Project Structure

```
ubuntu-miracast-server/
├── src/miracast_server/
│   ├── app.py              # Application entry point, lifecycle, signal wiring
│   ├── advertiser.py       # P2P Group Owner creation and WFD advertisement
│   ├── connection.py       # WPS PIN arming, DHCP, AP-STA-CONNECTED monitoring
│   ├── p2p_supplicant.py   # Dedicated wpa_supplicant instance manager
│   ├── rtsp.py             # RTSP protocol parsing and WFD message building
│   ├── receiver.py         # RTSP client (connects to source) + GStreamer pipeline
│   ├── config.py           # Configuration management with validation
│   ├── history.py          # Session history persistence
│   ├── models.py           # Data models with validation
│   ├── service.py          # Systemd service manager and headless mode
│   ├── utils.py            # Security-validated wpa_cli helpers
│   └── ui/
│       ├── main_window.py  # Main application window
│       ├── display_view.py # Video display with fullscreen support
│       ├── sessions_view.py# Session history browser
│       └── settings_view.py# Configuration UI
├── tests/                  # pytest test suite (250 tests)
├── scripts/                # Security audit scripts
├── .github/workflows/      # CI/CD (lint, test, security, release)
├── docs/                   # User documentation
├── specs/                  # Design specifications
└── .kiro/                  # AI agent configuration + protocol knowledge
```

## Development

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests (250 tests)
make test

# Run linting (ruff + mypy)
make lint

# Format code (ruff)
make format

# Run with coverage
make coverage

# Generate changelog
make changelog
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full development guide.

## CI/CD

Every push and pull request runs automated checks:

- **Lint** — Ruff check + format verification
- **Type Check** — mypy static analysis (advisory)
- **Test** — 250 tests with coverage reporting
- **Security Scan** — bandit SAST + custom subprocess safety audit
- **Commit Lint** — conventional commits enforcement

Releases are automated via tag push (`v*.*.*`):
- Changelog generated from conventional commits (git-cliff)
- Python sdist built and attached
- Debian `.deb` package built and attached
- GitHub Release created (pre-release for `-beta`/`-rc` tags)

Dependency updates are managed by Dependabot (weekly scans for pip + GitHub Actions).

## Related Projects

- [ubuntu-miracast-client](https://github.com/arongate/ubuntu-miracast-client) — the companion Miracast source (sender) application

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [lazycast](https://github.com/homeworkc/lazycast) for the proven Autonomous GO + WPS PIN approach
- [wpa_supplicant](https://w1.fi/wpa_supplicant/) for Wi-Fi Direct P2P support
- [GStreamer](https://gstreamer.freedesktop.org/) for media pipeline infrastructure
- [GTK](https://gtk.org/) and [libadwaita](https://gnome.pages.gitlab.gnome.org/libadwaita/) for the UI framework
- The Wi-Fi Display (Miracast) specification by the Wi-Fi Alliance
