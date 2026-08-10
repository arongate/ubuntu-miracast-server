# Testing Specification

## Ubuntu Miracast Server (Sink) v1.0.0

**Document Version:** 1.0  
**Date:** 2026-08-10  
**Status:** Draft

---

## 1. Test Strategy

### 1.1 Overview

The testing strategy employs a layered approach: unit tests for individual modules (RTSP parsing, state machine, config), integration tests for component interactions (P2P → RTSP → Media pipeline flow), and manual tests for hardware-dependent functionality (actual Wi-Fi Direct connections, video display).

### 1.2 Test Framework & Tools

| Tool | Version | Purpose |
|------|---------|---------|
| pytest | >=7.0.0 | Test runner and assertions |
| pytest-cov | >=4.0.0 | Code coverage measurement |
| pytest-asyncio | >=0.21.0 | Async/threaded test support |
| unittest.mock | stdlib | Mocking external dependencies |
| flake8 | >=6.0.0 | Static analysis (lint) |
| mypy | >=1.0.0 | Type checking |
| black | >=23.0.0 | Code formatting verification |

### 1.3 Test Execution

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=miracast_server --cov-report=html

# Run specific module tests
pytest tests/test_rtsp_server.py
pytest tests/test_p2p_advertiser.py

# Lint checks
flake8 src/
mypy src/
black --check src/
```

### 1.4 CI Integration

Tests run automatically via GitHub Actions on:
- Every push to any branch
- Every pull request to main

CI workflow (`.github/workflows/ci.yml`) steps:
1. Install system dependencies (GStreamer, GTK 4 dev libs)
2. `make lint` — flake8 + black check + mypy
3. `make test` — pytest with coverage
4. Upload coverage report as artifact

**CI Environment Notes:**
- Tests run without a display server (Xvfb not needed for unit tests)
- GStreamer elements validated via `Gst.ElementFactory.find()` mocks
- wpa_cli subprocess calls fully mocked

---

## 2. Test Categories

### 2.1 Unit Tests

Isolated tests for individual classes and functions with all external dependencies mocked. Focus areas:
- RTSP message parsing and serialization
- WFD capability encoding/decoding
- State machine transitions
- Config load/save
- Pipeline string construction

### 2.2 Integration Tests

Tests verifying correct interaction between components:
- P2PAdvertiser → MiracastSink state transitions
- RTSPServer → MiracastSink → MediaReceiver lifecycle
- Full M1–M7 negotiation sequence simulation

### 2.3 Manual Tests

Tests requiring physical hardware or desktop environment:
- Actual Wi-Fi Direct connection with a Miracast source
- Video display quality and latency measurement
- Audio playback verification
- Fullscreen mode on real display

---

## 3. Unit Test Specifications

### 3.1 RTSP Server Module (`tests/test_rtsp_server.py`)

#### TestRTSPMessage

| Test ID | Test Case | Validates |
|---------|-----------|-----------|
| TR-01 | `test_parse_options_request` | Parses `OPTIONS * RTSP/1.0` with CSeq and Require headers |
| TR-02 | `test_parse_get_parameter_request` | Parses GET_PARAMETER with body listing requested params |
| TR-03 | `test_parse_set_parameter_request` | Parses SET_PARAMETER with wfd_video_formats, wfd_audio_codecs body |
| TR-04 | `test_parse_setup_request` | Parses SETUP with Transport header (RTP/AVP/UDP;unicast;client_port=X) |
| TR-05 | `test_parse_play_request` | Parses PLAY with Session header |
| TR-06 | `test_parse_teardown_request` | Parses TEARDOWN with Session header |
| TR-07 | `test_parse_response` | Parses `RTSP/1.0 200 OK` response correctly |
| TR-08 | `test_serialize_options_response` | Serializes 200 OK with Public header listing methods |
| TR-09 | `test_serialize_get_parameter_response` | Serializes response with WFD capability body |
| TR-10 | `test_serialize_setup_response` | Serializes response with Transport and Session headers |
| TR-11 | `test_parse_malformed_request` | Raises/returns error for incomplete RTSP data |
| TR-12 | `test_parse_empty_body` | Handles request with Content-Length: 0 correctly |
| TR-13 | `test_cseq_tracking` | CSeq in response matches request CSeq |

#### TestWFDCapabilities

| Test ID | Test Case | Validates |
|---------|-----------|-----------|
| TR-14 | `test_encode_video_formats` | Encodes supported resolutions into WFD bitmap format |
| TR-15 | `test_encode_audio_codecs` | Encodes AAC-LC 48kHz stereo into correct format string |
| TR-16 | `test_encode_client_rtp_ports` | Formats port string as "RTP/AVP/UDP;unicast 1028 0 mode=play" |
| TR-17 | `test_encode_content_protection` | Returns "none" for no HDCP |
| TR-18 | `test_parse_set_video_format` | Parses source's selected video format from M4 body |
| TR-19 | `test_parse_set_audio_codec` | Parses source's selected audio codec from M4 body |
| TR-20 | `test_parse_presentation_url` | Extracts presentation URL from M4 body |
| TR-21 | `test_parse_transport_header` | Extracts client_port from SETUP Transport header |

#### TestRTSPServerLifecycle

| Test ID | Test Case | Validates |
|---------|-----------|-----------|
| TR-22 | `test_server_start_binds_port` | Server socket binds to configured port |
| TR-23 | `test_server_stop_closes_socket` | Server socket closed, thread joined |
| TR-24 | `test_accept_single_connection` | Accepts one TCP connection from source |
| TR-25 | `test_reject_second_connection` | Only one concurrent connection allowed |
| TR-26 | `test_session_timeout` | Session cleaned up after timeout with no activity |
| TR-27 | `test_keepalive_resets_timeout` | GET_PARAMETER with empty body resets session timer |

#### TestM1M7Flow

| Test ID | Test Case | Validates |
|---------|-----------|-----------|
| TR-28 | `test_m1_options_response` | Correct 200 OK with supported methods in Public header |
| TR-29 | `test_m2_options_sent` | Server sends OPTIONS to source after M1 |
| TR-30 | `test_m3_capability_response` | Response body contains all requested wfd_* parameters |
| TR-31 | `test_m4_set_parameter_accepted` | Returns 200 OK and stores negotiated params |
| TR-32 | `test_m4_unsupported_format_rejected` | Returns 415 for unsupported video format |
| TR-33 | `test_m5_setup_response` | Returns 200 with session ID and Transport header |
| TR-34 | `test_m6_play_triggers_callback` | on_play callback invoked with session ID |
| TR-35 | `test_m7_teardown_triggers_callback` | on_teardown callback invoked, session cleared |
| TR-36 | `test_full_m1_m7_sequence` | Complete negotiation succeeds in correct order |
| TR-37 | `test_out_of_order_rejected` | PLAY before SETUP returns 455 (Method Not Valid) |

---

### 3.2 P2P Advertiser Module (`tests/test_p2p_advertiser.py`)

#### TestP2PAdvertiser

| Test ID | Test Case | Validates |
|---------|-----------|-----------|
| TP-01 | `test_start_advertising_sets_wfd_subelems` | Calls `wpa_cli wfd_subelem_set` with correct device info sub-element |
| TP-02 | `test_start_advertising_enables_wifi_display` | Calls `wpa_cli set wifi_display 1` |
| TP-03 | `test_start_advertising_enters_listen` | Calls `wpa_cli p2p_listen` |
| TP-04 | `test_stop_advertising_clears_subelems` | Calls `wpa_cli set wifi_display 0` |
| TP-05 | `test_stop_advertising_cancels_listen` | Calls `wpa_cli p2p_stop_find` |
| TP-06 | `test_connection_requested_signal` | Emits `connection-requested` on P2P-GO-NEG-REQUEST event |
| TP-07 | `test_accept_connection_calls_p2p_connect` | Calls `wpa_cli p2p_connect <addr> pbc` |
| TP-08 | `test_group_formed_signal` | Emits `group-formed` on P2P-GROUP-STARTED event |
| TP-09 | `test_dhcp_client_started_as_client` | Runs `dhclient` when sink is P2P client |
| TP-10 | `test_dnsmasq_started_as_go` | Starts dnsmasq when sink is P2P Group Owner |
| TP-11 | `test_ip_assigned_signal` | Emits `ip-assigned` after DHCP completes |
| TP-12 | `test_peer_disconnected_signal` | Emits `peer-disconnected` on P2P-GROUP-REMOVED |
| TP-13 | `test_disconnect_peer_removes_group` | Calls `wpa_cli p2p_group_remove <interface>` |
| TP-14 | `test_wfd_subelem_encoding` | Device info sub-element encodes port, type, and throughput correctly |
| TP-15 | `test_custom_device_name` | Sets device name via `wpa_cli set device_name <name>` |
| TP-16 | `test_advertiser_error_on_wpa_cli_failure` | Emits `advertiser-error` when wpa_cli returns non-zero |
| TP-17 | `test_is_advertising_state` | Returns True after start, False after stop |

---

### 3.3 Media Receiver Module (`tests/test_media_receiver.py`)

#### TestMediaReceiver

| Test ID | Test Case | Validates |
|---------|-----------|-----------|
| TM-01 | `test_pipeline_construction_video_audio` | Pipeline string contains udpsrc, rtpmp2tdepay, tsdemux, h264parse, avdec_h264, videoconvert, sink + aacparse, avdec_aac, autoaudiosink |
| TM-02 | `test_pipeline_construction_hw_accel` | Uses vaapih264dec when available |
| TM-03 | `test_pipeline_construction_headless` | Uses autovideosink instead of gtk4paintablesink |
| TM-04 | `test_pipeline_port_configuration` | udpsrc port matches configured rtp_port |
| TM-05 | `test_start_sets_playing` | Pipeline set_state(PLAYING) called |
| TM-06 | `test_stop_sets_null` | Pipeline set_state(NULL) called |
| TM-07 | `test_pause_sets_paused` | Pipeline set_state(PAUSED) called |
| TM-08 | `test_get_paintable_returns_paintable` | Returns GdkPaintable from gtk4paintablesink property |
| TM-09 | `test_get_paintable_headless_returns_none` | Returns None when headless=True |
| TM-10 | `test_bus_error_emits_signal` | GStreamer ERROR message emits `pipeline-error` signal |
| TM-11 | `test_bus_eos_stops_pipeline` | EOS message triggers pipeline stop |
| TM-12 | `test_stats_collection` | StreamStats populated with bitrate, fps, resolution |
| TM-13 | `test_mute_unmute` | Audio sink volume set to 0.0/restored on mute/unmute |
| TM-14 | `test_volume_control` | Audio sink volume property updated correctly |
| TM-15 | `test_hw_accel_fallback` | Falls back to avdec_h264 if vaapi unavailable |
| TM-16 | `test_dynamic_pad_handling` | tsdemux pad-added signal correctly links to downstream |

---

### 3.4 MiracastSink Module (`tests/test_sink.py`)

#### TestMiracastSink

| Test ID | Test Case | Validates |
|---------|-----------|-----------|
| TS-01 | `test_initial_state_idle` | State is IDLE on construction |
| TS-02 | `test_start_transitions_to_advertising` | `start()` changes state to ADVERTISING |
| TS-03 | `test_stop_from_advertising` | `stop()` returns to IDLE |
| TS-04 | `test_connection_request_transitions_connecting` | P2P connection request → CONNECTING state |
| TS-05 | `test_ip_assigned_transitions_negotiating` | IP assignment → NEGOTIATING, RTSP server started |
| TS-06 | `test_play_transitions_streaming` | RTSP PLAY → STREAMING, media receiver started |
| TS-07 | `test_teardown_transitions_disconnected` | RTSP TEARDOWN → DISCONNECTED → ADVERTISING |
| TS-08 | `test_disconnect_stops_all` | `disconnect()` stops RTSP + media + P2P |
| TS-09 | `test_source_connected_signal` | Signal emitted with SourceInfo on connection |
| TS-10 | `test_source_disconnected_signal` | Signal emitted when source disconnects |
| TS-11 | `test_stream_started_signal` | Signal emitted with StreamInfo on PLAY |
| TS-12 | `test_error_returns_to_advertising` | Error during streaming → cleanup → ADVERTISING |
| TS-13 | `test_get_source_info_during_stream` | Returns SourceInfo with name, address, IP |
| TS-14 | `test_get_source_info_when_idle` | Returns None |
| TS-15 | `test_auto_readvertise_after_disconnect` | Automatically returns to ADVERTISING after DISCONNECTED |

---

### 3.5 Config Module (`tests/test_config.py`)

#### TestConfig

| Test ID | Test Case | Validates |
|---------|-----------|-----------|
| TC-01 | `test_default_config_created` | Default config with all sections created when no file exists |
| TC-02 | `test_set_and_get` | Values set via `set()` are retrievable via `get()` |
| TC-03 | `test_save_and_reload` | Config persists correctly through save/reload cycle |
| TC-04 | `test_nonexistent_key_returns_default` | `get()` returns default for missing key |
| TC-05 | `test_nonexistent_section_returns_default` | `get()` returns default for missing section |
| TC-06 | `test_get_device_name_fallback` | Returns hostname when device_name is empty |
| TC-07 | `test_get_rtsp_port_default` | Returns 7236 from default config |
| TC-08 | `test_corrupted_config_fallback` | Malformed JSON falls back to defaults |
| TC-09 | `test_config_file_permissions` | File created with 0600 permissions |
| TC-10 | `test_directories_created` | Parent directories created if missing |

---

### 3.6 Service Module (`tests/test_service.py`)

#### TestServiceManager

| Test ID | Test Case | Validates |
|---------|-----------|-----------|
| TSV-01 | `test_is_service_enabled_true` | Returns True when systemctl reports "enabled" |
| TSV-02 | `test_is_service_enabled_false` | Returns False when not enabled |
| TSV-03 | `test_is_service_running_true` | Returns True when systemctl reports "active" |
| TSV-04 | `test_is_service_running_false` | Returns False when not running |
| TSV-05 | `test_enable_service_creates_file` | Creates .service file at correct path |
| TSV-06 | `test_enable_service_reloads_daemon` | Calls `systemctl --user daemon-reload` |
| TSV-07 | `test_disable_service_removes_file` | Removes .service file after disabling |
| TSV-08 | `test_start_service` | Calls `systemctl --user start` |
| TSV-09 | `test_stop_service` | Calls `systemctl --user stop` |
| TSV-10 | `test_service_file_content` | Generated .service file has correct ExecStart, Restart, etc. |
| TSV-11 | `test_enable_failure_raises` | Raises RuntimeError on subprocess failure |

---

## 4. Integration Test Specifications (`tests/test_integration.py`)

### 4.1 P2P → Sink Flow

| Test ID | Test Case | Validates |
|---------|-----------|-----------|
| TI-01 | `test_p2p_connection_starts_rtsp_server` | Group formation triggers RTSP server start on correct port |
| TI-02 | `test_p2p_disconnect_stops_rtsp_server` | Peer disconnect stops RTSP server and pipeline |
| TI-03 | `test_p2p_disconnect_during_streaming` | Pipeline and RTSP cleaned up, state returns to Advertising |

### 4.2 RTSP → Media Pipeline Flow

| Test ID | Test Case | Validates |
|---------|-----------|-----------|
| TI-04 | `test_play_starts_media_receiver` | M6 PLAY triggers MediaReceiver.start() |
| TI-05 | `test_teardown_stops_media_receiver` | M7 TEARDOWN triggers MediaReceiver.stop() |
| TI-06 | `test_negotiated_params_configure_pipeline` | RTP port from negotiation used in pipeline udpsrc |

### 4.3 Full Session Simulation

| Test ID | Test Case | Validates |
|---------|-----------|-----------|
| TI-07 | `test_full_session_lifecycle` | Idle → Advertising → Connecting → Negotiating → Streaming → Disconnected → Advertising |
| TI-08 | `test_sequential_sessions` | After first session teardown, second source can connect successfully |
| TI-09 | `test_error_recovery` | Pipeline error during streaming → cleanup → return to Advertising |

### 4.4 Config Integration

| Test ID | Test Case | Validates |
|---------|-----------|-----------|
| TI-10 | `test_config_port_used_by_rtsp_server` | RTSP server binds to port from config |
| TI-11 | `test_config_device_name_advertised` | Device name from config set in wpa_supplicant |
| TI-12 | `test_config_hw_accel_affects_pipeline` | hw_accel=False uses software decoder |

---

## 5. Manual Test Procedures

### 5.1 End-to-End Miracast Session

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Launch `ubuntu-miracast-server` | Window appears showing "Waiting for connection..." |
| 2 | On source device (Windows/Android), search for wireless displays | Server appears with configured device name |
| 3 | Connect from source | Server shows "Connecting..." then "Negotiating..." |
| 4 | Wait for stream to begin | Video from source displayed in server window |
| 5 | Verify audio | Audio from source plays through server speakers |
| 6 | Press F11 | Video enters fullscreen |
| 7 | Press Escape | Video exits fullscreen |
| 8 | Click Disconnect | Stream stops, returns to waiting screen |
| 9 | Disconnect from source side | Same cleanup, returns to waiting |

### 5.2 Service Mode

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Run `ubuntu-miracast-server --service --name "Living Room TV"` | Process starts, logs show "Advertising as Living Room TV" |
| 2 | Connect from source device | Logs show negotiation, stream starts |
| 3 | Verify video output (autovideosink opens window) | Video displayed |
| 4 | Kill service process | Clean shutdown logged |
| 5 | Enable systemd service via UI Settings | Service file created, service starts |
| 6 | `systemctl --user status ubuntu-miracast-server` | Shows active (running) |
| 7 | Reboot, verify service auto-starts | Service running after login |

### 5.3 Latency Measurement

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Display millisecond timer on source screen | Timer visible on both screens |
| 2 | Photograph both screens simultaneously | |
| 3 | Measure time difference | Latency < 200ms |

### 5.4 Error Recovery

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Start streaming session | Video playing |
| 2 | Disconnect source Wi-Fi abruptly (airplane mode) | Server detects timeout, returns to advertising |
| 3 | Reconnect source and cast again | New session works correctly |

### 5.5 Settings Persistence

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open Settings → change device name to "Test Sink" | Field updated |
| 2 | Save settings | Success feedback |
| 3 | Restart application | Device name shows "Test Sink" |
| 4 | Source discovers device | Shows "Test Sink" in discovery list |

---

## 6. Test Coverage Targets

| Module | Target Coverage | Critical Paths |
|--------|----------------|----------------|
| `rtsp_server.py` | ≥90% | Message parsing, M1-M7 flow, error responses |
| `p2p_advertiser.py` | ≥80% | wfd_subelems encoding, event parsing, lifecycle |
| `media_receiver.py` | ≥75% | Pipeline construction, state management, stats |
| `sink.py` | ≥85% | State machine transitions, signal emission |
| `config.py` | ≥90% | Load/save, defaults, get/set |
| `service.py` | ≥80% | Enable/disable, status checks, file generation |
| **Overall** | **≥80%** | — |

---

## 7. Mocking Strategy

| External Dependency | Mock Approach |
|--------------------|---------------|
| `subprocess.run` / `subprocess.Popen` (wpa_cli) | Patch to return predefined stdout/stderr; simulate event output |
| `subprocess.run` (systemctl) | Patch to verify correct arguments |
| `subprocess.Popen` (dhclient/dnsmasq) | Patch; simulate IP assignment |
| `socket.socket` (RTSP server) | Use real sockets on localhost for integration tests; mock for unit tests |
| `Gst.Pipeline` | Mock `set_state()`, `get_state()`; simulate bus messages |
| `Gst.ElementFactory.find` | Return mock/None to test HW accel detection |
| `GLib.idle_add` | Patch to execute callback immediately in tests |
| `threading.Thread` | Patch to prevent actual threads in pure unit tests; allow in integration tests |
| File I/O (config) | Use `tempfile.TemporaryDirectory` |
| `time.sleep` | Patch to avoid delays |

### 7.1 RTSP Test Helpers

```python
class MockRTSPClient:
    """Simulates a Miracast source connecting to the RTSP server."""

    def __init__(self, host: str, port: int):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))
        self.cseq = 0

    def send_options(self) -> RTSPMessage:
        """Send M1 OPTIONS and return parsed response."""

    def send_get_parameter(self, params: list[str]) -> RTSPMessage:
        """Send M3 GET_PARAMETER and return capability response."""

    def send_set_parameter(self, params: dict) -> RTSPMessage:
        """Send M4 SET_PARAMETER and return response."""

    def send_setup(self, uri: str, client_port: int) -> RTSPMessage:
        """Send M5 SETUP and return response with session ID."""

    def send_play(self, uri: str, session_id: str) -> RTSPMessage:
        """Send M6 PLAY and return response."""

    def send_teardown(self, uri: str, session_id: str) -> RTSPMessage:
        """Send M7 TEARDOWN and return response."""
```

### 7.2 wpa_cli Event Simulation

```python
WPA_CLI_EVENTS = {
    "go_neg_request": "P2P-GO-NEG-REQUEST aa:bb:cc:dd:ee:ff dev_passwd_id=4",
    "group_started": "P2P-GROUP-STARTED p2p-wlan0-0 client ssid=\"DIRECT-ab\" "
                     "go_dev_addr=aa:bb:cc:dd:ee:ff",
    "group_removed": "P2P-GROUP-REMOVED p2p-wlan0-0 client",
    "device_found": "P2P-DEVICE-FOUND aa:bb:cc:dd:ee:ff p2p_dev_addr=aa:bb:cc:dd:ee:ff "
                    "name='Source Phone' config_methods=0x188",
}
```

---

## 8. Test Data

### 8.1 Sample RTSP Messages

```python
M1_OPTIONS_REQUEST = (
    b"OPTIONS * RTSP/1.0\r\n"
    b"CSeq: 1\r\n"
    b"Require: org.wfa.wfd1.0\r\n"
    b"\r\n"
)

M3_GET_PARAMETER_REQUEST = (
    b"GET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0\r\n"
    b"CSeq: 2\r\n"
    b"Content-Type: text/parameters\r\n"
    b"Content-Length: 83\r\n"
    b"\r\n"
    b"wfd_video_formats\r\n"
    b"wfd_audio_codecs\r\n"
    b"wfd_client_rtp_ports\r\n"
    b"wfd_content_protection\r\n"
)

M4_SET_PARAMETER_REQUEST = (
    b"SET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0\r\n"
    b"CSeq: 3\r\n"
    b"Content-Type: text/parameters\r\n"
    b"Content-Length: 150\r\n"
    b"\r\n"
    b"wfd_video_formats: 00 00 02 02 00000001 00000000 00000000 00 0000 0000 00 none none\r\n"
    b"wfd_audio_codecs: AAC 00000001 00\r\n"
    b"wfd_presentation_URL: rtsp://192.168.49.1/wfd1.0/streamid=0 none\r\n"
)

M5_SETUP_REQUEST = (
    b"SETUP rtsp://192.168.49.1/wfd1.0/streamid=0 RTSP/1.0\r\n"
    b"CSeq: 4\r\n"
    b"Transport: RTP/AVP/UDP;unicast;client_port=1028\r\n"
    b"\r\n"
)

M6_PLAY_REQUEST = (
    b"PLAY rtsp://192.168.49.1/wfd1.0/streamid=0 RTSP/1.0\r\n"
    b"CSeq: 5\r\n"
    b"Session: 12345678\r\n"
    b"\r\n"
)

M7_TEARDOWN_REQUEST = (
    b"TEARDOWN rtsp://192.168.49.1/wfd1.0/streamid=0 RTSP/1.0\r\n"
    b"CSeq: 6\r\n"
    b"Session: 12345678\r\n"
    b"\r\n"
)
```

### 8.2 Sample WFD Capability Response

```python
SAMPLE_M3_RESPONSE_BODY = (
    "wfd_video_formats: 00 00 02 02 0001FFFF 1FFFFFFF 00000FFF 00 0000 0000 00 none none\r\n"
    "wfd_audio_codecs: AAC 00000003 00\r\n"
    "wfd_client_rtp_ports: RTP/AVP/UDP;unicast 1028 0 mode=play\r\n"
    "wfd_content_protection: none\r\n"
)
```

### 8.3 Sample Config (for test fixtures)

```python
SAMPLE_CONFIG = {
    "general": {
        "device_name": "Test Sink",
        "auto_accept": True,
        "log_level": "INFO",
        "start_fullscreen": False,
    },
    "network": {
        "rtsp_port": 7236,
        "rtp_port": 1028,
        "p2p_interface": "wlan0",
        "listen_channel": 0,
    },
    "display": {
        "preferred_resolution": "1920x1080",
        "show_stream_info": True,
        "hw_accel": True,
    },
    "advanced": {
        "session_timeout": 30,
        "keep_alive_interval": 15,
        "buffer_size_ms": 100,
    },
}
```

---

## 9. Known Test Limitations

| Limitation | Reason | Mitigation |
|-----------|--------|------------|
| No actual Wi-Fi Direct testing in CI | Requires P2P-capable hardware | wpa_cli subprocess fully mocked; manual test procedures documented |
| No real GStreamer pipeline testing | Requires display server and GStreamer runtime | Pipeline string construction validated; element existence checked via mock |
| GTK widget tests limited | Requires running display server | Logic separated from GTK widgets; UI tested manually |
| RTSP integration tests use localhost | Real Miracast uses P2P interface | MockRTSPClient simulates source behavior over TCP loopback |
| No actual Miracast source in CI | Requires second device | Full M1-M7 simulated via MockRTSPClient |
| Audio output not verifiable in CI | No audio device | Audio pipeline construction validated; playback tested manually |

---

## 10. Test Organization

```
tests/
├── __init__.py
├── conftest.py                  # Shared fixtures (mock config, tmp dirs, event helpers)
├── test_rtsp_server.py          # TR-01 through TR-37
├── test_p2p_advertiser.py       # TP-01 through TP-17
├── test_media_receiver.py       # TM-01 through TM-16
├── test_sink.py                 # TS-01 through TS-15
├── test_config.py               # TC-01 through TC-10
├── test_service.py              # TSV-01 through TSV-11
├── test_integration.py          # TI-01 through TI-12
└── helpers/
    ├── __init__.py
    ├── mock_rtsp_client.py      # MockRTSPClient class
    └── wpa_cli_fixtures.py      # WPA_CLI_EVENTS and response fixtures
```
