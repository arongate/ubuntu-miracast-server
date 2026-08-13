# Getting Started

This guide walks you through setting up Ubuntu Miracast Server from scratch — from verifying hardware compatibility to receiving your first wireless screen cast.

## 1. Verify Prerequisites

### Hardware

You need a Wi-Fi adapter that supports **P2P (Wi-Fi Direct)**. Most modern Intel and Qualcomm adapters do.

```bash
# Check if your Wi-Fi adapter supports P2P
iw phy | grep -A 5 "Supported interface modes"
# Look for "P2P-device" or "P2P-GO" in the output
```

If you see `P2P-device`, `P2P-client`, and `P2P-GO` listed, your adapter is compatible.

**Known compatible adapters:**
- Intel Wi-Fi 6 AX200/AX201/AX210
- Intel Wireless-AC 8265/9260
- Qualcomm Atheros QCA6174/QCA9377

### Software

| Requirement | Minimum Version | Check Command |
|---|---|---|
| Ubuntu | 24.04 LTS | `lsb_release -a` |
| Python | 3.10 | `python3 --version` |
| GStreamer | 1.20 | `gst-launch-1.0 --version` |
| GTK 4 | 4.6 | `pkg-config --modversion gtk4` |
| wpa_supplicant | 2.10 | `wpa_supplicant -v` |

### wpa_supplicant Configuration

wpa_supplicant must be configured with P2P support. On Ubuntu 24.04, the default NetworkManager setup typically handles this. Verify:

```bash
# Check that wpa_supplicant is running with P2P
sudo wpa_cli interface
# Should show a "p2p-dev-wlanX" interface
```

If no P2P interface appears, you may need to configure wpa_supplicant manually:

```bash
# /etc/wpa_supplicant/wpa_supplicant.conf
ctrl_interface=/var/run/wpa_supplicant
update_config=1
device_name=Ubuntu-PC
device_type=1-0050F204-1
p2p_go_intent=15

# Restart
sudo systemctl restart wpa_supplicant
```

## 2. Install System Dependencies

```bash
sudo apt update
sudo apt install \
    python3-gi python3-gst-1.0 \
    gir1.2-gtk-4.0 gir1.2-adw-1 \
    gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
    gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
    wpasupplicant
```

**Recommended extras:**

```bash
# Hardware-accelerated video decoding (VA-API for Intel/AMD)
sudo apt install gstreamer1.0-vaapi intel-media-va-driver

# DHCP server for P2P Group Owner mode
sudo apt install dnsmasq

# Development tools (if building from source)
sudo apt install python3-venv python3-pip git
```

## 3. Install Ubuntu Miracast Server

### Option A: From Source (recommended)

```bash
git clone https://github.com/yourusername/ubuntu-miracast-server.git
cd ubuntu-miracast-server

# Create virtual environment with system site-packages
# (required so Python can access GTK and GStreamer system bindings)
python3 -m venv .venv --system-site-packages
source .venv/bin/activate

# Install the package in editable mode
pip install -e .

# Verify installation
ubuntu-miracast-server --help
```

### Option B: From Debian Package

```bash
# Download the .deb file from releases
sudo apt install ./ubuntu-miracast-server_1.0.0-1_all.deb
```

### Option C: Using uv (fast Python package manager)

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and set up
git clone https://github.com/yourusername/ubuntu-miracast-server.git
cd ubuntu-miracast-server
uv venv .venv --python /usr/bin/python3 --system-site-packages
source .venv/bin/activate
uv pip install -e .
```

## 4. First Run

### Launch the Application

```bash
ubuntu-miracast-server
```

You should see the GTK window appear with the message "Waiting for Miracast source..." and your Wi-Fi adapter will begin advertising as a Miracast sink.

### Connect a Source Device

From your source device:

1. **Android:** Settings → Display → Cast / Wireless Display → Enable → Select "Ubuntu Miracast Server"
2. **Windows 10/11:** Settings → System → Display → Connect to a wireless display (or Win+K)
3. **Ubuntu (with ubuntu-miracast-client):** Launch the client and select your server from discovered devices

### What Happens

1. The source device discovers your server via Wi-Fi Direct P2P
2. A P2P connection is formed (WPS Push Button Configuration)
3. RTSP negotiation establishes streaming parameters (resolution, codec, ports)
4. The source begins streaming H.264 video (+ AAC audio) over RTP/MPEG-TS
5. The video appears in the server window (auto-fullscreen if configured)

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| F11 | Toggle fullscreen |
| Escape | Exit fullscreen |
| Double-click | Toggle fullscreen |

## 5. Troubleshooting

### Single-Radio Wi-Fi Limitation (Concurrent Connection Failure)

**Symptom:** PIN exchange succeeds, "P2P-GO-NEG-SUCCESS" appears in logs, but the connection drops immediately with `EAP-FAILURE` or `Authentication request to the driver failed`.

**Cause:** Most laptop Wi-Fi adapters have a single radio that cannot simultaneously maintain your regular Wi-Fi connection (e.g., to your home router on channel 11 / 2.4 GHz) AND a P2P group connection (typically on 5 GHz). When the P2P group tries to form on a different frequency, the driver fails.

**This affects:** Intel AX200/AX201/AX210, most single-radio adapters when connected to a router.

**Solutions (pick one):**

1. **Disconnect from your Wi-Fi router before casting** (simplest):
   ```bash
   # Disconnect from home WiFi
   nmcli device disconnect wlo1
   
   # Start the server
   ubuntu-miracast-server
   
   # After casting, reconnect
   nmcli device connect wlo1
   ```

2. **Use a secondary USB Wi-Fi adapter** dedicated to P2P — this eliminates the channel conflict entirely.

3. **Use Ethernet** for internet connectivity instead of Wi-Fi, freeing the wireless adapter for P2P.

4. **Run a dedicated wpa_supplicant instance** for P2P (advanced). This is the approach used by [miraclecast](https://github.com/albfan/miraclecast). See [Service Mode documentation](service-mode.md) for details.

> **Note:** This is a hardware/driver limitation, not a software bug. The P2P protocol negotiation works correctly — the failure occurs at the driver level when attempting concurrent multi-channel operation.

### "No P2P interface found"

Your Wi-Fi adapter doesn't expose a P2P device interface via wpa_supplicant.

```bash
# Verify wpa_supplicant is running
sudo systemctl status wpa_supplicant

# Check for P2P interfaces
sudo wpa_cli interface

# If using NetworkManager, it may manage wpa_supplicant differently
nmcli device wifi list  # Verify WiFi is up
```

### "Failed to enable wifi_display"

wpa_supplicant may not support the `wifi_display` feature. Ensure you have version 2.10+ and it was compiled with CONFIG_WIFI_DISPLAY=y.

### Black screen after connection

The GStreamer pipeline may not have the required decoder plugins:

```bash
# Verify decoder availability
gst-inspect-1.0 avdec_h264
gst-inspect-1.0 tsdemux
gst-inspect-1.0 rtpmp2tdepay

# If missing, install:
sudo apt install gstreamer1.0-libav gstreamer1.0-plugins-bad
```

### No audio

```bash
# Verify AAC decoder
gst-inspect-1.0 avdec_aac

# Verify PulseAudio/PipeWire sink
gst-inspect-1.0 pulsesink
```

### Permission issues with wpa_cli

The application uses `sudo wpa_cli` for P2P operations. Ensure your user can run wpa_cli:

```bash
# Add to wpa_supplicant group (if available)
sudo usermod -aG netdev $USER

# Or configure sudoers for passwordless wpa_cli
echo "$USER ALL=(ALL) NOPASSWD: /sbin/wpa_cli" | sudo tee /etc/sudoers.d/miracast
```

## 6. Next Steps

- [Configuration](configuration.md) — customize device name, ports, and behavior
- [Service Mode](service-mode.md) — run headless as a systemd service
- [Architecture](architecture.md) — understand the internals
