"""Miracast Receiver — RTSP client and GStreamer pipeline management.

In the Wi-Fi Display (Miracast) protocol, the Sink (us) connects TO the
Source's (phone's) RTSP server on port 7236. The Sink is the RTSP client.

RTSP Message Flow (from lazycast/Wi-Fi Display spec):
  Sink connects to Source:7236
  M1: Source → OPTIONS → Sink replies 200 OK
  M2: Sink → OPTIONS → Source replies 200 OK
  M3: Source → GET_PARAMETER (query capabilities) → Sink replies with WFD params
  M4: Source → SET_PARAMETER (chosen params) → Sink replies 200 OK
  M5: Source → SET_PARAMETER (wfd_trigger_method: SETUP) → Sink replies 200 OK
  M6: Sink → SETUP rtsp://source/wfd1.0/streamid=0 → Source replies with Session
  M7: Sink → PLAY rtsp://source/wfd1.0/streamid=0 → Source replies 200 OK, starts RTP
"""

import errno
import fcntl
import logging
import os
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime

import gi

gi.require_version("GLib", "2.0")
gi.require_version("Gst", "1.0")
from gi.repository import GLib, GObject, Gst

from miracast_server.models import IncomingConnection, ReceiverStats, SourceInfo

logger = logging.getLogger(__name__)

# Ensure GStreamer is initialized
Gst.init(None)

# Codec whitelist for pipeline construction
_ALLOWED_VIDEO_CODECS = {"H264"}
_ALLOWED_AUDIO_CODECS = {"AAC"}

# Stream monitoring constants
_RTP_TIMEOUT_SECONDS = 15.0  # seconds without RTP data before declaring stream lost
_PIPELINE_STATE_TIMEOUT_SECONDS = 5.0
_STATS_INTERVAL_SECONDS = 1.0
_FRAME_DROP_WARNING_THRESHOLD = 0.05  # 5%
_FRAME_DROP_WINDOW_SECONDS = 10

# Queue bounds
_QUEUE_MAX_BUFFERS = 200
_QUEUE_MAX_BYTES = 10485760  # 10 MB
_QUEUE_MAX_TIME = 1000000000  # 1 second in nanoseconds

# RTSP connection constants
_RTSP_CONNECT_TIMEOUT = 30.0  # seconds to try connecting to source
_RTSP_RECV_TIMEOUT = 30.0  # seconds to wait for RTSP messages
_RTSP_BUFFER_SIZE = 16384
_RTSP_PORT = 7236  # Standard WFD RTSP port on the source
_RTP_PORT = 1028  # Our local RTP receive port


def _validate_port(port: int) -> None:
    """Validate that a port is in the allowed range."""
    if not isinstance(port, int) or port < 1024 or port > 65535:
        raise ValueError(f"Port must be integer in range 1024-65535, got {port}")


def _validate_video_codec(codec: str) -> None:
    """Validate video codec against whitelist."""
    if codec not in _ALLOWED_VIDEO_CODECS:
        raise ValueError(
            f"Video codec '{codec}' not in whitelist: {_ALLOWED_VIDEO_CODECS}"
        )


def _validate_audio_codec(codec: str) -> None:
    """Validate audio codec against whitelist."""
    if codec not in _ALLOWED_AUDIO_CODECS:
        raise ValueError(
            f"Audio codec '{codec}' not in whitelist: {_ALLOWED_AUDIO_CODECS}"
        )


class PipelineBuilder:
    """Constructs GStreamer pipelines for Miracast stream reception.

    Handles codec validation, hardware decode detection, and mode-specific
    sink selection (GUI vs headless).
    """

    def __init__(self, headless: bool = False):
        """Initialize the pipeline builder.

        Args:
            headless: If True, use fakesink instead of gtk4paintablesink.
        """
        self._headless = headless

    def build_pipeline(
        self,
        rtp_port: int,
        video_codec: str = "H264",
        audio_codec: str = "AAC",
        audio_enabled: bool = True,
        use_hw_decode: bool = True,
    ) -> Gst.Pipeline:
        """Build the receive pipeline.

        Pipeline structure:
          udpsrc → rtpmp2tdepay → tsdemux → h264parse → decoder → videoconvert → sink
          (audio branch): aacparse → avdec_aac → audioconvert → pulsesink

        Args:
            rtp_port: UDP port for RTP reception (1024-65535).
            video_codec: Video codec name (must be in whitelist).
            audio_codec: Audio codec name (must be in whitelist).
            audio_enabled: Whether to include the audio branch.
            use_hw_decode: Whether to attempt hardware-accelerated decoding.

        Returns:
            Configured Gst.Pipeline ready to be set to PLAYING.

        Raises:
            ValueError: If port or codec validation fails.
            RuntimeError: If pipeline construction fails.
        """
        _validate_port(rtp_port)
        _validate_video_codec(video_codec)
        if audio_enabled:
            _validate_audio_codec(audio_codec)

        pipeline = Gst.Pipeline.new("miracast-receive")

        # ─── Source and demux ─────────────────────────────────────────
        udpsrc = Gst.ElementFactory.make("udpsrc", "udpsrc")
        if not udpsrc:
            raise RuntimeError("Failed to create udpsrc element")
        udpsrc.set_property("port", rtp_port)
        udpsrc.set_property("buffer-size", 2 * 1024 * 1024)  # 2 MB buffer
        caps = Gst.Caps.from_string(
            "application/x-rtp,media=video,clock-rate=90000,encoding-name=MP2T"
        )
        udpsrc.set_property("caps", caps)

        rtpdepay = Gst.ElementFactory.make("rtpmp2tdepay", "rtpdepay")
        if not rtpdepay:
            raise RuntimeError("Failed to create rtpmp2tdepay element")

        tsdemux = Gst.ElementFactory.make("tsdemux", "demux")
        if not tsdemux:
            raise RuntimeError("Failed to create tsdemux element")

        # ─── Video branch ─────────────────────────────────────────────
        video_queue = self._make_queue("video_queue")
        h264parse = Gst.ElementFactory.make("h264parse", "h264parse")
        if not h264parse:
            raise RuntimeError("Failed to create h264parse element")

        decoder = self._make_decoder(use_hw_decode)
        videoconvert = Gst.ElementFactory.make("videoconvert", "videoconvert")
        if not videoconvert:
            raise RuntimeError("Failed to create videoconvert element")

        videosink = self._make_video_sink()

        # Add all video elements to pipeline
        for elem in [udpsrc, rtpdepay, tsdemux, video_queue, h264parse,
                     decoder, videoconvert, videosink]:
            pipeline.add(elem)

        # Link source chain
        udpsrc.link(rtpdepay)
        rtpdepay.link(tsdemux)

        # Link video branch (static pads)
        video_queue.link(h264parse)
        h264parse.link(decoder)
        decoder.link(videoconvert)
        videoconvert.link(videosink)

        # ─── Audio branch (optional) ─────────────────────────────────
        if audio_enabled:
            audio_queue = self._make_queue("audio_queue")
            aacparse = Gst.ElementFactory.make("aacparse", "aacparse")
            audiodec = Gst.ElementFactory.make("avdec_aac", "audiodec")
            audioconvert = Gst.ElementFactory.make("audioconvert", "audioconvert")
            audiosink = Gst.ElementFactory.make("pulsesink", "audiosink")

            if not all([aacparse, audiodec, audioconvert, audiosink]):
                # Fallback: try autoaudiosink
                audiosink = Gst.ElementFactory.make("autoaudiosink", "audiosink")
                if not audiosink:
                    logger.warning("No audio sink available, disabling audio")
                    audio_enabled = False

            if audio_enabled:
                for elem in [audio_queue, aacparse, audiodec, audioconvert, audiosink]:
                    pipeline.add(elem)
                audio_queue.link(aacparse)
                aacparse.link(audiodec)
                audiodec.link(audioconvert)
                audioconvert.link(audiosink)

        # ─── Dynamic pad linking for tsdemux ──────────────────────────
        def on_pad_added(demux, pad):
            pad_name = pad.get_name()
            caps_str = pad.get_current_caps().to_string() if pad.get_current_caps() else ""
            logger.debug("tsdemux pad added: %s caps=%s", pad_name, caps_str)

            if "video" in caps_str or "h264" in caps_str.lower():
                sink_pad = video_queue.get_static_pad("sink")
                if sink_pad and not sink_pad.is_linked():
                    pad.link(sink_pad)
                    logger.debug("Linked video pad")
            elif audio_enabled and ("audio" in caps_str or "aac" in caps_str.lower()):
                audio_q = pipeline.get_by_name("audio_queue")
                if audio_q:
                    sink_pad = audio_q.get_static_pad("sink")
                    if sink_pad and not sink_pad.is_linked():
                        pad.link(sink_pad)
                        logger.debug("Linked audio pad")

        tsdemux.connect("pad-added", on_pad_added)

        return pipeline

    def _make_queue(self, name: str) -> Gst.Element:
        """Create a queue element with configured bounds."""
        queue = Gst.ElementFactory.make("queue", name)
        if not queue:
            raise RuntimeError(f"Failed to create queue element '{name}'")
        queue.set_property("max-size-buffers", _QUEUE_MAX_BUFFERS)
        queue.set_property("max-size-bytes", _QUEUE_MAX_BYTES)
        queue.set_property("max-size-time", _QUEUE_MAX_TIME)
        return queue

    def _make_decoder(self, use_hw: bool) -> Gst.Element:
        """Create a video decoder, attempting hardware acceleration first."""
        if use_hw:
            # Try vaapi first
            for hw_decoder in ["vaapidecodebin", "nvh264dec"]:
                factory = Gst.ElementFactory.find(hw_decoder)
                if factory:
                    decoder = Gst.ElementFactory.make(hw_decoder, "videodec")
                    if decoder:
                        logger.info("Using hardware decoder: %s", hw_decoder)
                        return decoder

        # Fallback to software decoder
        decoder = Gst.ElementFactory.make("avdec_h264", "videodec")
        if not decoder:
            raise RuntimeError("Failed to create video decoder (avdec_h264)")
        logger.info("Using software decoder: avdec_h264")
        return decoder

    def _make_video_sink(self) -> Gst.Element:
        """Create the video sink element based on mode."""
        if self._headless:
            sink = Gst.ElementFactory.make("fakesink", "videosink")
            if not sink:
                raise RuntimeError("Failed to create fakesink element")
            sink.set_property("sync", True)
            return sink

        # Try gtk4paintablesink first
        sink = Gst.ElementFactory.make("gtk4paintablesink", "videosink")
        if sink:
            logger.info("Using gtk4paintablesink for video output")
            return sink

        # Fallback to autovideosink
        sink = Gst.ElementFactory.make("autovideosink", "videosink")
        if not sink:
            raise RuntimeError("Failed to create video sink element")
        logger.info("Using autovideosink for video output")
        return sink


class MiracastReceiver(GObject.Object):
    """Manages RTSP client session and GStreamer pipeline for receiving Miracast streams.

    In Wi-Fi Display, the Sink (us) connects TO the Source's RTSP server.
    After the P2P connection is established (AP-STA-CONNECTED + DHCP),
    we connect to the source's port 7236 and negotiate the stream.

    GObject Signals:
      - stream-started: Stream playback has begun.
      - stream-stopped(object): Stream has ended normally. Payload is ReceiverStats.
      - stream-error(str): An error occurred during streaming.
      - stats-updated(object): Stream statistics updated. Payload is dict.
      - resolution-changed(object): Stream resolution changed. Payload is tuple.
    """

    __gsignals__ = {
        "stream-started": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "stream-stopped": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "stream-error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "stats-updated": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "resolution-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(
        self,
        rtsp_port: int = 7236,
        rtp_port: int = 1028,
        headless: bool = False,
        audio_enabled: bool = True,
    ):
        """Initialize the receiver.

        Args:
            rtsp_port: TCP port for RTSP on the source (default 7236).
            rtp_port: UDP port for RTP media reception on our side.
            headless: Whether to use fakesink (service mode).
            audio_enabled: Whether to enable audio decoding.
        """
        super().__init__()
        self._rtsp_port = rtsp_port
        self._rtp_port = rtp_port
        self._headless = headless
        self._audio_enabled = audio_enabled

        self._pipeline: Gst.Pipeline | None = None
        self._pipeline_builder = PipelineBuilder(headless=headless)
        self._rtsp_socket: socket.socket | None = None
        self._rtsp_thread: threading.Thread | None = None
        self._stats_thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()

        # Session state
        self._connection: IncomingConnection | None = None
        self._session_id: str = ""
        self._cseq: int = 100  # Our CSeq counter for outgoing requests (M2, M6, M7)
        self._source_info: SourceInfo | None = None
        self._source_ip: str = ""

        # Stats tracking
        self._start_time: datetime | None = None
        self._data_received: int = 0
        self._frames_decoded: int = 0
        self._frames_dropped: int = 0
        self._peak_bitrate: float = 0.0
        self._current_bitrate: float = 0.0
        self._resolution: tuple[int, int] = (0, 0)
        self._last_rtp_time: float = 0.0
        self._errors: int = 0
        self._use_hw_decode: bool = True

        # WFD negotiated parameters
        self._video_codec: str = "H264"
        self._audio_codec: str = "AAC"

    @property
    def is_receiving(self) -> bool:
        """Whether the receiver is currently active."""
        return self._running

    @property
    def pipeline(self) -> Gst.Pipeline | None:
        """The GStreamer pipeline (for UI binding to paintable sink)."""
        return self._pipeline

    @property
    def source_info(self) -> SourceInfo | None:
        """Information about the connected source."""
        return self._source_info

    def start_receiving(self, connection: IncomingConnection) -> None:
        """Start the RTSP client session with the connected source.

        Connects to the source's RTSP server at <peer_ip>:7236 and
        performs the WFD RTSP negotiation (M1-M7).

        Args:
            connection: The active P2P connection with the source.
        """
        if self._running:
            logger.warning("start_receiving called while already receiving")
            return

        self._connection = connection
        self._source_ip = connection.peer_ip
        self._running = True
        self._start_time = datetime.now()
        self._source_info = SourceInfo(
            name=connection.peer_name,
            address=connection.peer_address,
            model="",
        )

        logger.info(
            "Starting RTSP client session — connecting to source %s:%d",
            self._source_ip, self._rtsp_port,
        )

        # Start RTSP client thread
        self._rtsp_thread = threading.Thread(
            target=self._rtsp_client_session,
            name="rtsp-client",
            daemon=True,
        )
        self._rtsp_thread.start()

    def stop_receiving(self) -> ReceiverStats:
        """Stop receiving and clean up all resources.

        Returns:
            ReceiverStats with session statistics.
        """
        self._running = False

        # Send TEARDOWN if we have an active session
        if self._rtsp_socket and self._session_id:
            try:
                self._send_teardown()
            except (OSError, socket.error):
                pass

        # Stop pipeline
        if self._pipeline:
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None

        # Close RTSP socket
        if self._rtsp_socket:
            try:
                self._rtsp_socket.close()
            except OSError:
                pass
            self._rtsp_socket = None

        # Join threads
        if self._rtsp_thread:
            self._rtsp_thread.join(timeout=5.0)
            if self._rtsp_thread.is_alive():
                logger.warning("RTSP thread did not stop within 5 seconds")
            self._rtsp_thread = None

        if self._stats_thread:
            self._stats_thread.join(timeout=5.0)
            self._stats_thread = None

        # Build stats
        stats = self._build_stats()
        logger.info("Receiving stopped. Duration: %ds", stats.duration)
        return stats

    def _build_stats(self) -> ReceiverStats:
        """Build ReceiverStats from current session data."""
        end_time = datetime.now()
        duration = 0
        if self._start_time:
            duration = int((end_time - self._start_time).total_seconds())

        return ReceiverStats(
            start_time=self._start_time or end_time,
            end_time=end_time,
            duration=duration,
            data_received=self._data_received,
            average_bitrate=self._current_bitrate,
            peak_bitrate=self._peak_bitrate,
            frames_decoded=self._frames_decoded,
            frames_dropped=self._frames_dropped,
            errors=self._errors,
            resolution=self._resolution,
            codec=self._video_codec,
        )

    def _rtsp_client_session(self) -> None:
        """RTSP client session running in a dedicated thread.

        Connects to the source's RTSP server and handles the WFD
        message sequence (M1-M7) from the sink perspective.
        """
        try:
            # Connect to source's RTSP server with retries
            self._rtsp_socket = self._connect_to_source()
            if not self._rtsp_socket:
                return

            sock = self._rtsp_socket
            source_ip = self._source_ip

            logger.info("RTSP connected to source %s:%d", source_ip, self._rtsp_port)

            # === M1: Source sends OPTIONS, we reply ===
            data = self._recv_message(sock)
            if not data:
                raise RuntimeError("No M1 received from source")
            logger.info("M1 received: %s", data[:80])

            # Parse CSeq from M1
            m1_cseq = self._parse_cseq(data)
            m1_response = (
                f"RTSP/1.0 200 OK\r\n"
                f"CSeq: {m1_cseq}\r\n"
                f"Public: org.wfa.wfd1.0, SET_PARAMETER, GET_PARAMETER\r\n"
                f"\r\n"
            )
            sock.sendall(m1_response.encode())
            logger.debug("M1 response sent")

            # === M2: We send OPTIONS to source ===
            self._cseq += 1
            m2_request = (
                f"OPTIONS * RTSP/1.0\r\n"
                f"CSeq: {self._cseq}\r\n"
                f"Require: org.wfa.wfd1.0\r\n"
                f"\r\n"
            )
            sock.sendall(m2_request.encode())
            logger.debug("M2 sent (OPTIONS to source)")

            # Read M2 response
            data = self._recv_message(sock)
            if not data:
                raise RuntimeError("No M2 response from source")
            logger.debug("M2 response: %s", data[:80])

            # === M3: Source sends GET_PARAMETER, we reply with capabilities ===
            data = self._recv_message(sock)
            if not data:
                raise RuntimeError("No M3 received from source")
            logger.info("M3 received (capability query)")

            m3_cseq = self._parse_cseq(data)
            capability_body = self._build_capability_body(data)
            m3_response = (
                f"RTSP/1.0 200 OK\r\n"
                f"CSeq: {m3_cseq}\r\n"
                f"Content-Type: text/parameters\r\n"
                f"Content-Length: {len(capability_body)}\r\n"
                f"\r\n"
                f"{capability_body}"
            )
            sock.sendall(m3_response.encode())
            logger.debug("M3 response sent (capabilities)")

            # === M4: Source sends SET_PARAMETER (chosen params), we reply OK ===
            data = self._recv_message(sock)
            if not data:
                raise RuntimeError("No M4 received from source")
            logger.info("M4 received (parameters set)")

            m4_cseq = self._parse_cseq(data)
            # Parse chosen parameters from M4
            self._parse_m4_params(data)
            m4_response = f"RTSP/1.0 200 OK\r\nCSeq: {m4_cseq}\r\n\r\n"
            sock.sendall(m4_response.encode())
            logger.debug("M4 response sent")

            # === M5: Source sends SET_PARAMETER (trigger SETUP), we reply OK ===
            data = self._recv_message(sock)
            if not data:
                raise RuntimeError("No M5 received from source")
            logger.info("M5 received (trigger SETUP)")

            m5_cseq = self._parse_cseq(data)
            m5_response = f"RTSP/1.0 200 OK\r\nCSeq: {m5_cseq}\r\n\r\n"
            sock.sendall(m5_response.encode())
            logger.debug("M5 response sent")

            # === M6: We send SETUP ===
            self._cseq += 1
            m6_request = (
                f"SETUP rtsp://{source_ip}/wfd1.0/streamid=0 RTSP/1.0\r\n"
                f"CSeq: {self._cseq}\r\n"
                f"Transport: RTP/AVP/UDP;unicast;client_port={self._rtp_port}\r\n"
                f"\r\n"
            )
            sock.sendall(m6_request.encode())
            logger.debug("M6 sent (SETUP)")

            # Read M6 response — extract Session ID and server_port
            data = self._recv_message(sock)
            if not data:
                raise RuntimeError("No M6 response from source")
            logger.info("M6 response: %s", data[:200])

            self._session_id = self._parse_session_id(data)
            server_port = self._parse_server_port(data)
            logger.info("Session: %s, server_port: %s", self._session_id, server_port)

            # === Start GStreamer pipeline BEFORE sending PLAY ===
            # The pipeline will be ready to receive RTP as soon as source starts sending
            self._start_pipeline()

            # === M7: We send PLAY ===
            self._cseq += 1
            m7_request = (
                f"PLAY rtsp://{source_ip}/wfd1.0/streamid=0 RTSP/1.0\r\n"
                f"CSeq: {self._cseq}\r\n"
                f"Session: {self._session_id}\r\n"
                f"\r\n"
            )
            sock.sendall(m7_request.encode())
            logger.debug("M7 sent (PLAY)")

            # Read M7 response
            data = self._recv_message(sock)
            if not data:
                raise RuntimeError("No M7 response from source")
            logger.info("M7 response received — streaming active!")

            GLib.idle_add(self.emit, "stream-started")

            # === Streaming phase: handle keep-alive and teardown ===
            self._streaming_loop(sock)

        except socket.timeout:
            if self._running:
                error_msg = "RTSP connection timeout"
                logger.error(error_msg)
                GLib.idle_add(self.emit, "stream-error", error_msg)
        except (ConnectionRefusedError, ConnectionResetError) as e:
            if self._running:
                error_msg = f"RTSP connection refused: {e}"
                logger.error(error_msg)
                GLib.idle_add(self.emit, "stream-error", error_msg)
        except RuntimeError as e:
            if self._running:
                error_msg = f"RTSP negotiation failed: {e}"
                logger.error(error_msg)
                GLib.idle_add(self.emit, "stream-error", error_msg)
        except OSError as e:
            if self._running:
                error_msg = f"RTSP session error: {e}"
                logger.error(error_msg)
                GLib.idle_add(self.emit, "stream-error", error_msg)
        except Exception as e:
            if self._running:
                error_msg = f"Unexpected RTSP error: {e}"
                logger.error(error_msg)
                GLib.idle_add(self.emit, "stream-error", error_msg)

    def _connect_to_source(self) -> socket.socket | None:
        """Connect to the source's RTSP server with retries.

        The source may not have its RTSP server ready immediately after
        DHCP completes, so we retry for up to _RTSP_CONNECT_TIMEOUT seconds.

        Returns:
            Connected socket or None on failure.
        """
        deadline = time.monotonic() + _RTSP_CONNECT_TIMEOUT
        attempt = 0

        while self._running and time.monotonic() < deadline:
            attempt += 1
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.settimeout(5.0)
                sock.connect((self._source_ip, self._rtsp_port))
                sock.settimeout(_RTSP_RECV_TIMEOUT)
                logger.info(
                    "Connected to source RTSP server %s:%d (attempt %d)",
                    self._source_ip, self._rtsp_port, attempt,
                )
                return sock
            except (ConnectionRefusedError, socket.timeout, OSError) as e:
                logger.debug(
                    "RTSP connect attempt %d failed: %s — retrying in 1s",
                    attempt, e,
                )
                try:
                    sock.close()
                except OSError:
                    pass
                time.sleep(1.0)

        if self._running:
            error_msg = (
                f"Failed to connect to source RTSP at {self._source_ip}:{self._rtsp_port} "
                f"after {attempt} attempts"
            )
            logger.error(error_msg)
            GLib.idle_add(self.emit, "stream-error", error_msg)
        return None

    def _streaming_loop(self, sock: socket.socket) -> None:
        """Handle the streaming phase — keep-alive and teardown detection.

        After PLAY, the source may send:
        - GET_PARAMETER (keep-alive) — reply 200 OK
        - SET_PARAMETER (parameter updates) — reply 200 OK
        - TEARDOWN — reply 200 OK and stop
        """
        # Set socket to non-blocking for the streaming loop
        sock.setblocking(False)

        while self._running:
            try:
                data_bytes = sock.recv(_RTSP_BUFFER_SIZE)
                if not data_bytes:
                    # Connection closed by source
                    logger.info("Source closed RTSP connection")
                    self._stop_pipeline_and_emit()
                    return

                data = data_bytes.decode("utf-8", errors="replace")

                if "wfd_trigger_method: TEARDOWN" in data or "TEARDOWN" in data.split("\r\n")[0]:
                    logger.info("Received TEARDOWN from source")
                    # Reply OK
                    cseq = self._parse_cseq(data)
                    response = f"RTSP/1.0 200 OK\r\nCSeq: {cseq}\r\n\r\n"
                    try:
                        sock.sendall(response.encode())
                    except OSError:
                        pass
                    self._stop_pipeline_and_emit()
                    return

                # Handle keep-alive and other messages
                if "GET_PARAMETER" in data or "SET_PARAMETER" in data:
                    cseq = self._parse_cseq(data)
                    response = f"RTSP/1.0 200 OK\r\nCSeq: {cseq}\r\n\r\n"
                    try:
                        sock.sendall(response.encode())
                    except OSError:
                        pass

                    # If SET_PARAMETER contains new video formats, re-start player
                    if "wfd_video_formats" in data:
                        logger.info("Source sent updated video formats")

            except socket.error as e:
                err = e.args[0]
                if err == errno.EAGAIN or err == errno.EWOULDBLOCK:
                    # No data available, sleep briefly
                    time.sleep(0.01)
                else:
                    if self._running:
                        logger.error("Socket error in streaming loop: %s", e)
                        self._stop_pipeline_and_emit()
                    return

    def _recv_message(self, sock: socket.socket) -> str | None:
        """Receive a complete RTSP message from the socket.

        Returns decoded string or None on error/timeout.
        """
        try:
            data = sock.recv(_RTSP_BUFFER_SIZE)
            if not data:
                return None

            text = data.decode("utf-8", errors="replace")

            # Check if we need to read more (Content-Length)
            content_length = 0
            for line in text.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    try:
                        content_length = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                    break

            # If there's a body, ensure we have it all
            if content_length > 0:
                header_end = data.find(b"\r\n\r\n")
                if header_end >= 0:
                    body_start = header_end + 4
                    body_received = len(data) - body_start
                    while body_received < content_length:
                        more = sock.recv(
                            min(content_length - body_received, _RTSP_BUFFER_SIZE)
                        )
                        if not more:
                            break
                        data += more
                        body_received += len(more)

            return data.decode("utf-8", errors="replace")
        except socket.timeout:
            return None
        except OSError:
            return None

    def _parse_cseq(self, data: str) -> int:
        """Extract CSeq value from an RTSP message."""
        for line in data.split("\r\n"):
            if line.lower().startswith("cseq:"):
                try:
                    return int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
        return 0

    def _parse_session_id(self, data: str) -> str:
        """Extract Session ID from an RTSP response."""
        for line in data.split("\r\n"):
            if line.lower().startswith("session:"):
                # Session: <id>;timeout=30  or  Session: <id>
                value = line.split(":", 1)[1].strip()
                return value.split(";")[0].strip()
        return "0"

    def _parse_server_port(self, data: str) -> str:
        """Extract server_port from Transport header in SETUP response."""
        for line in data.split("\r\n"):
            if line.lower().startswith("transport:"):
                # Look for server_port=NNNNN
                parts = line.split(";")
                for part in parts:
                    if "server_port=" in part:
                        return part.split("=")[1].strip()
        return ""

    def _build_capability_body(self, m3_data: str) -> str:
        """Build the M3 capability response body.

        Replies to the source's GET_PARAMETER query with our supported
        WFD parameters (matching lazycast's proven working values).
        """
        msg = "wfd_client_rtp_ports: RTP/AVP/UDP;unicast {} 0 mode=play\r\n".format(
            self._rtp_port
        )
        msg += "wfd_audio_codecs: AAC 00000001 00\r\n"
        # Video formats: support most resolutions up to 1080p
        # Bit 0x0001FEFF = disable 1080p60 (bit 16), keep rest
        msg += "wfd_video_formats: 00 00 02 10 0001FEFF 3FFFFFFF 00000FFF 00 0000 0000 00 none none\r\n"
        msg += "wfd_3d_video_formats: none\r\n"
        msg += "wfd_coupled_sink: none\r\n"
        msg += "wfd_connector_type: 05\r\n"
        msg += "wfd_uibc_capability: none\r\n"
        msg += "wfd_standby_resume_capability: none\r\n"
        msg += "wfd_content_protection: none\r\n"

        # Respond to vendor-specific queries if present
        if "wfd_idr_request_capability" in m3_data:
            msg += "wfd_idr_request_capability: 1\r\n"

        return msg

    def _parse_m4_params(self, data: str) -> None:
        """Parse M4 SET_PARAMETER message for chosen stream parameters."""
        # Extract body (after \r\n\r\n)
        parts = data.split("\r\n\r\n", 1)
        if len(parts) < 2:
            return
        body = parts[1]

        for line in body.split("\r\n"):
            if line.startswith("wfd_video_formats:"):
                # Parse resolution from the video formats line
                # Format: native timing_flags profile_flags level max_hres max_vres ...
                logger.debug("M4 video formats: %s", line)
            elif line.startswith("wfd_audio_codecs:"):
                if "LPCM" in line:
                    self._audio_codec = "LPCM"
                else:
                    self._audio_codec = "AAC"
                logger.debug("M4 audio codec: %s", self._audio_codec)
            elif line.startswith("wfd_client_rtp_ports:"):
                # Source may override RTP port
                parts_rtp = line.split()
                if len(parts_rtp) >= 3:
                    try:
                        port = int(parts_rtp[2])
                        if 1024 <= port <= 65535:
                            self._rtp_port = port
                            logger.info("M4 set RTP port to %d", port)
                    except ValueError:
                        pass

    def _send_teardown(self) -> None:
        """Send TEARDOWN request to the source."""
        if not self._rtsp_socket or not self._session_id:
            return
        self._cseq += 1
        teardown = (
            f"TEARDOWN rtsp://{self._source_ip}/wfd1.0/streamid=0 RTSP/1.0\r\n"
            f"CSeq: {self._cseq}\r\n"
            f"Session: {self._session_id}\r\n"
            f"\r\n"
        )
        self._rtsp_socket.sendall(teardown.encode())

    def _start_pipeline(self) -> None:
        """Build and start the GStreamer pipeline."""
        try:
            self._pipeline = self._pipeline_builder.build_pipeline(
                rtp_port=self._rtp_port,
                video_codec=self._video_codec,
                audio_codec=self._audio_codec if self._audio_enabled else "AAC",
                audio_enabled=self._audio_enabled,
                use_hw_decode=self._use_hw_decode,
            )

            # Set up bus message handling
            bus = self._pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect("message", self._on_bus_message)

            # Start playing (don't block waiting for state - it may take time for autovideosink)
            ret = self._pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError("Pipeline failed to transition to PLAYING")

            self._last_rtp_time = time.monotonic()
            logger.info("GStreamer pipeline started, listening on UDP port %d", self._rtp_port)

            # Add a pad probe on udpsrc to track RTP data arrival
            udpsrc = self._pipeline.get_by_name("udpsrc")
            if udpsrc:
                src_pad = udpsrc.get_static_pad("src")
                if src_pad:
                    src_pad.add_probe(
                        Gst.PadProbeType.BUFFER,
                        self._rtp_buffer_probe,
                        None,
                    )

            # Start stats monitoring thread
            self._stats_thread = threading.Thread(
                target=self._stats_monitor_loop,
                name="stats-monitor",
                daemon=True,
            )
            self._stats_thread.start()

        except Exception as e:
            error_msg = f"Failed to start pipeline: {e}"
            logger.error(error_msg)
            self._errors += 1
            GLib.idle_add(self.emit, "stream-error", error_msg)

    def _rtp_buffer_probe(self, pad, info, user_data) -> Gst.PadProbeReturn:
        """Pad probe callback to track RTP data arrival for stream health."""
        buf = info.get_buffer()
        if buf:
            self._data_received += buf.get_size()
            self._last_rtp_time = time.monotonic()
        return Gst.PadProbeReturn.OK

    def _stop_pipeline_and_emit(self) -> None:
        """Stop pipeline and emit stream-stopped with stats."""
        if self._pipeline:
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None

        stats = self._build_stats()
        self._running = False
        GLib.idle_add(self.emit, "stream-stopped", stats)

    def _on_bus_message(self, bus: Gst.Bus, message: Gst.Message) -> bool:
        """Handle GStreamer bus messages."""
        msg_type = message.type

        if msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            error_msg = f"Pipeline error: {err.message}"
            logger.error("%s (debug: %s)", error_msg, debug)
            self._errors += 1

            # Try hardware decode fallback
            if self._use_hw_decode and "decode" in err.message.lower():
                logger.warning("Attempting software decode fallback")
                self._use_hw_decode = False
                GLib.idle_add(self._rebuild_pipeline_with_sw_decode)
            else:
                GLib.idle_add(self.emit, "stream-error", error_msg)

        elif msg_type == Gst.MessageType.EOS:
            logger.info("Pipeline received EOS")
            self._stop_pipeline_and_emit()

        elif msg_type == Gst.MessageType.STATE_CHANGED:
            if message.src == self._pipeline:
                old, new, pending = message.parse_state_changed()
                logger.debug("Pipeline state: %s -> %s", old.value_nick, new.value_nick)

        return True

    def _rebuild_pipeline_with_sw_decode(self) -> None:
        """Rebuild the pipeline with software decoding after HW failure."""
        if self._pipeline:
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
        self._start_pipeline()

    def _stats_monitor_loop(self) -> None:
        """Stats collection thread running at 1-second intervals."""
        last_bytes = 0
        frame_history: list[tuple[float, int, int]] = []

        while self._running and self._pipeline:
            time.sleep(_STATS_INTERVAL_SECONDS)

            if not self._running or not self._pipeline:
                break

            now = time.monotonic()

            try:
                current_bytes = self._data_received
                bytes_delta = current_bytes - last_bytes
                bitrate = bytes_delta * 8.0
                last_bytes = current_bytes

                self._current_bitrate = bitrate
                if bitrate > self._peak_bitrate:
                    self._peak_bitrate = bitrate

                frame_history.append((now, self._frames_decoded, self._frames_dropped))
                cutoff = now - _FRAME_DROP_WINDOW_SECONDS
                frame_history = [(t, d, dr) for t, d, dr in frame_history if t >= cutoff]

                if len(frame_history) >= 2:
                    first = frame_history[0]
                    last_entry = frame_history[-1]
                    decoded_delta = last_entry[1] - first[1]
                    dropped_delta = last_entry[2] - first[2]
                    if decoded_delta > 0:
                        drop_rate = dropped_delta / (decoded_delta + dropped_delta)
                        if drop_rate > _FRAME_DROP_WARNING_THRESHOLD:
                            logger.warning(
                                "Frame drop rate %.1f%% exceeds threshold",
                                drop_rate * 100,
                            )

                # Check for stream loss
                if self._last_rtp_time > 0:
                    silence = now - self._last_rtp_time
                    if silence >= _RTP_TIMEOUT_SECONDS:
                        error_msg = f"Stream lost: no RTP data for {silence:.1f}s"
                        logger.error(error_msg)
                        if self._pipeline:
                            self._pipeline.set_state(Gst.State.NULL)
                            self._pipeline = None
                        GLib.idle_add(self.emit, "stream-error", error_msg)
                        return

                stats_dict = {
                    "bitrate": bitrate,
                    "peak_bitrate": self._peak_bitrate,
                    "frames_decoded": self._frames_decoded,
                    "frames_dropped": self._frames_dropped,
                    "resolution": self._resolution,
                    "data_received": self._data_received,
                    "duration": int((datetime.now() - self._start_time).total_seconds())
                    if self._start_time
                    else 0,
                }
                GLib.idle_add(self.emit, "stats-updated", stats_dict)

            except Exception as e:
                logger.debug("Stats collection error: %s", e)

    def notify_rtp_data(self, byte_count: int) -> None:
        """Notify the receiver that RTP data was received.

        Args:
            byte_count: Number of bytes received.
        """
        self._data_received += byte_count
        self._last_rtp_time = time.monotonic()
