# Project Context

## Architecture

Ubuntu Miracast Server is a layered application:

```
App Layer (app.py)           — lifecycle, CLI, signal wiring
UI Layer (ui/)               — GTK views, user interaction
Core Layer (advertiser, connection, receiver, rtsp) — protocol logic
Data Layer (config, history, models)   — persistence, validation
Utility Layer (utils, service)         — security helpers, systemd
```

### Signal Flow

Components communicate via GObject signals. The flow is:

1. `Advertiser` → advertising-started(group_iface) → `ConnectionHandler` arms WPS PIN
2. `ConnectionHandler` → pin-display(pin) → UI shows PIN on screen
3. Source enters PIN → AP-STA-CONNECTED on group interface
4. `ConnectionHandler` → connection-received → `Receiver` starts RTSP
5. `Receiver` → stream-started/stopped/error → `History` records + UI updates
6. After stream ends → ConnectionHandler re-arms WPS PIN

### P2P Architecture (Autonomous Group Owner)

Uses `p2p_group_add persistent` to create a GO, then `wps_pin any <PIN>` on the GROUP interface.
This is the proven approach (lazycast/7herbert). See `.kiro/miracast-p2p-protocol.md`.

DO NOT use `p2p_listen` + GO Negotiation — it's unreliable and was the cause of all P2P failures.

### Threading

- Main thread: GTK event loop, signal handlers, UI updates
- P2P monitor thread: polls wpa_cli for P2P events
- RTSP thread: handles TCP RTSP session with source
- Stats thread: 1s interval pipeline queries
- GStreamer threads: internal decode/render (managed by GStreamer)

All cross-thread communication uses `GLib.idle_add()`.

## Module Dependency Map

```
app.py → advertiser, connection, receiver, config, history, service, ui/*
advertiser.py → utils
connection.py → utils, models
receiver.py → rtsp, models
rtsp.py → (standalone, no internal deps)
config.py → (standalone)
history.py → models
models.py → (standalone)
service.py → advertiser, connection, receiver, config, history
utils.py → (standalone)
ui/main_window.py → ui/display_view, ui/sessions_view, ui/settings_view
ui/display_view.py → (uses receiver via constructor injection)
ui/sessions_view.py → (uses history via constructor injection)
ui/settings_view.py → (uses config via constructor injection)
```

## External Dependencies

| System Binary | Used By | Purpose |
|---|---|---|
| `wpa_cli` | advertiser, connection | Wi-Fi Direct P2P control |
| `dhclient` | connection | DHCP client after P2P group formation |
| `dnsmasq` | connection | DHCP server when acting as P2P GO |
| `ip` | connection | Interface IP address queries |
| `systemctl` | service | systemd service management |

## File Locations (XDG)

| File | Path |
|------|------|
| Config | `~/.config/ubuntu-miracast-server/config.json` |
| History | `~/.local/share/ubuntu-miracast-server/history.json` |
| Logs | `~/.local/share/ubuntu-miracast-server/logs/miracast-server.log` |
| Service | `~/.config/systemd/user/ubuntu-miracast-server.service` |

## Testing Notes

- Tests use `tmp_path` fixture for file isolation
- External commands (wpa_cli, subprocess) are mocked in tests
- GStreamer elements are mocked (no display server needed for testing)
- Tests run without network, Wi-Fi, or root access

## Related Project

The companion project `ubuntu-miracast-client` (Miracast source/sender) lives in the same parent directory and shares conventions.
