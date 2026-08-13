# AGENTS.md

## Project Overview

Ubuntu Miracast Server — a Python 3.10+ GTK 4 desktop application that acts as a Miracast sink (Wi-Fi Display receiver) for Ubuntu. Receives wireless screen casts from phones, laptops, and other Miracast source devices via Wi-Fi Direct P2P.

## Dev Environment

- **Language:** Python 3.10+ (3.12 recommended)
- **UI:** GTK 4 + libadwaita (via PyGObject)
- **Media:** GStreamer 1.20+
- **Networking:** wpa_supplicant (via `wpa_cli` subprocess)
- **OS:** Ubuntu 24.04 LTS (Linux only)

### Setup

```bash
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -e ".[dev]"
```

The `--system-site-packages` flag is **required** — PyGObject and GStreamer bindings must come from system packages, not pip.

### System dependencies (must be installed via apt)

```bash
sudo apt install python3-gi python3-gst-1.0 \
    gir1.2-gtk-4.0 gir1.2-adw-1 \
    gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
    gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
    wpasupplicant
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific module tests
pytest tests/test_models.py -v
pytest tests/test_config.py -v

# With coverage
pytest tests/ --cov=miracast_server --cov-report=html
```

- Tests use `tmp_path` for file isolation
- External commands (wpa_cli, subprocess) are mocked
- GStreamer elements are mocked — no display server needed
- Tests run without network, Wi-Fi, or root access

## Linting & Formatting

```bash
# Format
black --line-length=100 src/ tests/
isort src/ tests/

# Lint
flake8 src/ tests/

# Type check
mypy src/
```

## Build & Run

```bash
# Run the application
ubuntu-miracast-server

# Service mode (headless, no GUI)
ubuntu-miracast-server --service

# With custom device name
ubuntu-miracast-server --name "My Display"

# Start in fullscreen
ubuntu-miracast-server --fullscreen
```

## Code Style

- **Formatter:** Black, line-length=100
- **Import sort:** isort (Black-compatible profile)
- **Type hints:** Required on all function signatures. Use `str | None` union syntax.
- **Docstrings:** Google-style on all public classes and methods.
- **Module structure:** imports → constants → classes → functions

## Architecture

```
src/miracast_server/
├── app.py              # Entry point, lifecycle, CLI, signal wiring
├── advertiser.py       # WFD sink P2P advertisement (wpa_supplicant)
├── connection.py       # Wi-Fi Direct connection handling + DHCP
├── rtsp.py             # RTSP protocol parsing (stateless, no I/O)
├── receiver.py         # GStreamer pipeline + RTSP session management
├── config.py           # JSON config with validation
├── history.py          # Session history persistence
├── models.py           # Data models with validation
├── service.py          # systemd service + headless mode
├── utils.py            # Security-validated wpa_cli helpers
└── ui/                 # GTK 4 views (MainWindow, Display, Sessions, Settings)
```

### Signal flow (GObject signals, all via GLib.idle_add from threads)

1. `Advertiser` → advertising-started → `ConnectionHandler` starts listening
2. `ConnectionHandler` → connection-received → `Receiver` starts RTSP
3. `Receiver` → stream-started/stopped/error → `History` records + UI updates
4. After stream ends → automatic return to advertising

### Threading rules

- **Never emit signals from non-main threads.** Always use `GLib.idle_add(self.emit, ...)`.
- Protect shared state with `threading.Lock`.
- Set `_running = False` before joining threads. Use 5-second join timeouts.
- Background threads use `daemon=True`.

## Security Rules (DO NOT VIOLATE)

- **No `shell=True`** in subprocess calls. Always list format.
- **Validate wpa_cli params** via `utils._validate_wpa_param()` before subprocess.
- **Validate codecs** against `utils.ALLOWED_VIDEO_CODECS` / `utils.ALLOWED_AUDIO_CODECS`.
- **RTSP input is size-limited** (8KB headers, 64KB body) before parsing.
- **Config/history files** use 0600 permissions with atomic writes.
- **Never log secret values** — reference by key name only.

## Key Conventions

- Config at `~/.config/ubuntu-miracast-server/config.json`
- History at `~/.local/share/ubuntu-miracast-server/history.json`
- Logs at `~/.local/share/ubuntu-miracast-server/logs/miracast-server.log`
- Service file at `~/.config/systemd/user/ubuntu-miracast-server.service`
- Atomic file writes: write to `.tmp` then `rename()`
- GStreamer elements named descriptively: `"videosink"`, `"udpsrc"`, `"demux"`

## Commit Conventions

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add WPS PIN authentication
fix: handle RTSP timeout during renegotiation
docs: add troubleshooting for 5GHz
test: add property tests for RTSP CSeq
```

## PR Instructions

- Branch from `main`: `feature/<name>`, `fix/<name>`, `docs/<name>`
- Run `pytest tests/` and `black --check src/` before committing
- PR title < 70 characters
- Do not push directly to `main`

## Known Hardware Constraints

- **Single-radio Wi-Fi adapters** cannot simultaneously maintain a regular Wi-Fi connection and a P2P group on different channels. This causes `EAP-FAILURE` / driver authentication failures after successful WPS exchange. Workaround: disconnect from Wi-Fi before Miracast, or use a second adapter.
- The P2P group interface name is `p2p-wlo1-N` (where N increments). It's created by the kernel during group formation and may take several seconds to appear.

## Do Not Modify

- `specs/` directory — design specifications (read-only reference)
- System-level config files outside the project directory
- Any file that would require root/sudo to write

## Related Project

The companion Miracast source (sender) is at `../ubuntu-miracast-client/` — shares Python/GTK/GStreamer conventions.
