# Service Mode

Ubuntu Miracast Server can run as a headless systemd user service — always advertising and ready to receive streams without a GUI window.

## Quick Start

```bash
# Run in service mode directly
ubuntu-miracast-server --service

# With a custom device name
ubuntu-miracast-server --service --name "Conference Room Display"
```

## systemd User Service

### Install and Enable

The application can generate and install its own systemd service file:

```bash
# Manual installation
mkdir -p ~/.config/systemd/user

cat > ~/.config/systemd/user/ubuntu-miracast-server.service << 'EOF'
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
EOF

# Reload systemd and enable
systemctl --user daemon-reload
systemctl --user enable ubuntu-miracast-server
systemctl --user start ubuntu-miracast-server
```

### Manage the Service

```bash
# Check status
systemctl --user status ubuntu-miracast-server

# View logs
journalctl --user -u ubuntu-miracast-server -f

# Stop
systemctl --user stop ubuntu-miracast-server

# Disable from starting on login
systemctl --user disable ubuntu-miracast-server
```

### Programmatic Management

The `ServerServiceManager` class provides install/enable/disable/start/stop with rollback on failure:

```python
from miracast_server.service import ServerServiceManager

mgr = ServerServiceManager()
mgr.install()   # Writes service file + daemon-reload (rolls back on failure)
mgr.enable()    # systemctl --user enable
mgr.start()     # systemctl --user start
mgr.stop()      # systemctl --user stop
mgr.disable()   # systemctl --user disable
mgr.uninstall() # Stops, disables, removes file, reloads
```

## How It Works

In service mode, the application:

1. Initializes `GLib.MainLoop` (no GTK, no window)
2. Uses `fakesink sync=true` instead of `gtk4paintablesink` for video output
3. Starts advertising immediately on launch
4. Accepts connections and receives streams headlessly
5. Records sessions to history on stream end
6. Returns to advertising after each session

### Idle Timeout

Configure `service.idle_timeout` (in seconds) to automatically shut down the service when idle:

```json
{
  "service": {
    "idle_timeout": 3600
  }
}
```

Set to `0` (default) to disable — the service runs indefinitely.

When enabled, the service exits with code 0 after the configured period of no active streams. systemd will not restart it (it's a clean exit, not a failure).

### Signal Handling

The service responds to:
- **SIGTERM** — graceful shutdown (stop receiver → stop advertising → exit)
- **SIGINT** — same as SIGTERM

On failure (crash, unexpected exit), systemd restarts the service after 5 seconds (`Restart=on-failure`, `RestartSec=5`).

## Configuration for Service Mode

Key configuration options relevant to service mode:

| Option | Description |
|--------|-------------|
| `general.device_name` | Name visible to Miracast sources |
| `network.auto_accept` | Should be `true` for unattended operation (auto-arms WPS PIN) |
| `service.idle_timeout` | Auto-shutdown after N seconds idle |
| `streaming.rtsp_port` | Must not conflict with other services |
| `network.rtp_port` | Must not conflict with other services |

## Firewall

If you have a firewall enabled, allow the required ports:

```bash
# RTSP control (TCP)
sudo ufw allow 7236/tcp comment "Miracast RTSP"

# RTP media (UDP)
sudo ufw allow 1028/udp comment "Miracast RTP"
```

## Troubleshooting

### Service fails to start

```bash
journalctl --user -u ubuntu-miracast-server --no-pager -n 50
```

Common causes:
- No P2P-capable Wi-Fi interface available
- wpa_supplicant not running
- Port 7236 already in use

### Service starts but devices can't find it

- Verify Wi-Fi is enabled and not in airplane mode
- Check that wpa_supplicant has P2P support: `sudo wpa_cli interface`
- Ensure no other application is using the P2P interface

### Lingering user services after logout

systemd user services stop when the user session ends. To keep them running after logout:

```bash
sudo loginctl enable-linger $USER
```
