"""Miracast Receiver — RTSP session handling and GStreamer pipeline management.

Handles the RTSP negotiation flow with the Miracast source, constructs and
manages the GStreamer receive/decode/render pipeline, and monitors stream health.
"""

import logging
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
from miracast_server.rtsp import (
    RTSPMethod,
    RTSPParseError,
    RTSPRequest,
    WFDParameters,
    build_capability_response_body,
    build_options_request,
    build_options_response,
    build_response,
    parse_rtsp_request,
    parse_wfd_parameters,
    validate_request_size,
    RTSP_OK,
    RTSP_BAD_REQUEST,
)

logger = logging.getLogger(__name__)

# Ensure GStreamer is initialized
Gst.init(None)

# Codec whitelist for pipeline construction
_ALLOWED_VIDEO_CODECS = {"H264"}
_ALLOWED_AUDIO_CODECS = {"AAC"}

# Stream monitoring constants
_RTP_TIMEOUT_SECONDS = 5.0
_PIPELINE_STATE_TIMEOUT_SECONDS = 5.0
_STATS_INTERVAL_SECONDS = 1.0
_FRAME_DROP_WARNING_THRESHOLD = 0.05  # 5%
_FRAME_DROP_WINDOW_SECONDS = 10
_RTSP_RENEGOTIATION_TIMEOUT = 10.0

# Queue bounds
_QUEUE_MAX_BUFFERS = 200
_QUEUE_MAX_BYTES = 10485760  # 10 MB
_QUEUE_MAX_TIME = 1000000000  # 1 second in nanoseconds

# RTSP socket constants
_RTSP_RECV_TIMEOUT = 30.0  # seconds to wait for initial RTSP
_RTSP_BUFFER_SIZE = 16384


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
    """Manages RTSP session and GStreamer pipeline for receiving Miracast streams.

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
            rtsp_port: TCP port for RTSP control session.
            rtp_port: UDP port for RTP media reception.
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
        self._wfd_params: WFDParameters | None = None
        self._session_id: str = ""
        self._cseq: int = 0
        self._source_info: SourceInfo | None = None

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
        """Start receiving a Miracast stream.

        Binds an RTSP socket to the P2P interface IP and starts the RTSP
        handler thread to negotiate with the source.

        Args:
            connection: The active P2P connection with the source.
        """
        if self._running:
            logger.warning("start_receiving called while already receiving")
            return

        self._connection = connection
        self._running = True
        self._start_time = datetime.now()
        self._source_info = SourceInfo(
            name=connection.peer_name,
            address=connection.peer_address,
            model="",
        )

        # Bind RTSP socket
        try:
            self._rtsp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._rtsp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._rtsp_socket.settimeout(_RTSP_RECV_TIMEOUT)
            # Bind to the P2P interface IP, not 0.0.0.0
            bind_ip = connection.our_ip
            self._rtsp_socket.bind((bind_ip, self._rtsp_port))
            self._rtsp_socket.listen(1)
            logger.info("RTSP server listening on %s:%d", bind_ip, self._rtsp_port)
        except OSError as e:
            error_msg = f"Failed to bind RTSP socket on {connection.our_ip}:{self._rtsp_port}: {e}"
            logger.error(error_msg)
            self._running = False
            GLib.idle_add(self.emit, "stream-error", error_msg)
            return

        # Start RTSP handler thread
        self._rtsp_thread = threading.Thread(
            target=self._rtsp_session_loop,
            name="rtsp-session",
            daemon=True,
        )
        self._rtsp_thread.start()

    def stop_receiving(self) -> ReceiverStats:
        """Stop receiving and clean up all resources.

        Returns:
            ReceiverStats with session statistics.
        """
        self._running = False

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
            codec=self._wfd_params.video_codec if self._wfd_params else "",
        )

    def _rtsp_session_loop(self) -> None:
        """RTSP session handler running in a dedicated thread.

        Accepts the incoming RTSP connection from the source and handles
        the WFD message sequence (M1-M7).
        """
        client_socket: socket.socket | None = None
        try:
            # Wait for the source to connect
            logger.debug("Waiting for RTSP connection...")
            client_socket, addr = self._rtsp_socket.accept()
            client_socket.settimeout(30.0)
            peer_ip = addr[0]
            logger.info("RTSP connection from %s:%d", peer_ip, addr[1])

            # NFR-S04: Validate that the RTSP connection comes from the P2P peer
            if self._connection and self._connection.peer_ip != "0.0.0.0":
                expected_peer = self._connection.peer_ip
                if peer_ip != expected_peer:
                    logger.error(
                        "Rejecting RTSP connection from %s — expected P2P peer %s",
                        peer_ip,
                        expected_peer,
                    )
                    client_socket.close()
                    GLib.idle_add(
                        self.emit,
                        "stream-error",
                        f"RTSP connection from unauthorized address {peer_ip}",
                    )
                    return

            # Track CSeq for outgoing requests (M2)
            self._cseq = 0
            # Track whether M2 has been sent
            m2_sent = False
            # Session activity timestamp for timeout tracking
            last_activity = time.monotonic()

            # Handle RTSP message sequence
            while self._running:
                # FR-RN15: Check RTSP session timeout (30s inactivity)
                if self._session_id:  # Only enforce during active session
                    idle_time = time.monotonic() - last_activity
                    if idle_time >= 30.0:
                        logger.warning("RTSP session timeout — no activity for 30s")
                        self._stop_pipeline_and_emit()
                        break

                data = self._recv_rtsp_message(client_socket)
                if not data:
                    # Check if it's just a timeout (no data) vs connection closed
                    if self._running and self._session_id:
                        # Socket timeout but session active — check session timeout
                        continue
                    break

                last_activity = time.monotonic()

                try:
                    validate_request_size(data)
                    request = parse_rtsp_request(data)
                except RTSPParseError as e:
                    logger.warning("Malformed RTSP request: %s", e)
                    error_resp = build_response(e.status_code, 0)
                    client_socket.sendall(error_resp.serialize())
                    continue

                response = self._handle_rtsp_request(request, client_socket)
                if response:
                    client_socket.sendall(response.serialize())

                # FR-RN03: After handling M1 (first OPTIONS from source), send M2
                if request.method == RTSPMethod.OPTIONS and not m2_sent:
                    m2_sent = True
                    self._cseq += 1
                    m2_request = build_options_request(self._cseq)
                    client_socket.sendall(m2_request)
                    logger.debug("Sent M2 (OPTIONS to source) CSeq=%d", self._cseq)
                    # Read and discard the M2 response from source
                    m2_response_data = self._recv_rtsp_message(client_socket)
                    if m2_response_data:
                        last_activity = time.monotonic()
                        logger.debug("Received M2 response from source")

        except socket.timeout:
            if self._running:
                error_msg = "RTSP connection timeout — no connection within 30 seconds"
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
        finally:
            if client_socket:
                try:
                    client_socket.close()
                except OSError:
                    pass

    def _recv_rtsp_message(self, sock: socket.socket) -> bytes | None:
        """Receive a complete RTSP message from the socket."""
        try:
            data = sock.recv(_RTSP_BUFFER_SIZE)
            if not data:
                return None

            # Check if we need to read more (Content-Length)
            text = data.decode("utf-8", errors="replace")
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
                        more = sock.recv(min(content_length - body_received, _RTSP_BUFFER_SIZE))
                        if not more:
                            break
                        data += more
                        body_received += len(more)

            return data
        except socket.timeout:
            return None
        except OSError:
            return None

    def _handle_rtsp_request(
        self, request: RTSPRequest, client_socket: socket.socket
    ):
        """Handle a parsed RTSP request and return the response."""
        from miracast_server.rtsp import RTSPResponse

        logger.debug("RTSP %s %s CSeq=%d", request.method.name, request.uri, request.cseq)

        if request.method == RTSPMethod.OPTIONS:
            return build_options_response(request.cseq)

        elif request.method == RTSPMethod.GET_PARAMETER:
            # FR-RN13: Distinguish M3 (capability query) from keep-alive (empty body)
            if not request.body or not request.body.strip():
                # Keep-alive: respond with 200 OK and no body
                return build_response(RTSP_OK, request.cseq)
            else:
                # M3: Source queries our capabilities
                body = build_capability_response_body(
                    rtsp_port=self._rtsp_port,
                    rtp_port=self._rtp_port,
                )
                return build_response(RTSP_OK, request.cseq, body=body)

        elif request.method == RTSPMethod.SET_PARAMETER:
            # M4: Source sets selected parameters
            self._wfd_params = parse_wfd_parameters(request.body)
            if self._wfd_params.rtp_port:
                self._rtp_port = self._wfd_params.rtp_port
            if self._wfd_params.resolution != (0, 0):
                self._resolution = self._wfd_params.resolution
            logger.info(
                "WFD params set: codec=%s rtp_port=%d resolution=%s",
                self._wfd_params.video_codec,
                self._rtp_port,
                self._resolution,
            )
            return build_response(RTSP_OK, request.cseq)

        elif request.method == RTSPMethod.SETUP:
            # M5: Transport setup
            self._session_id = f"{int(time.time()):08X}"
            headers = {
                "Transport": f"RTP/AVP/UDP;unicast;client_port={self._rtp_port}",
                "Session": f"{self._session_id};timeout=30",
            }
            return build_response(RTSP_OK, request.cseq, headers=headers)

        elif request.method == RTSPMethod.PLAY:
            # M6: Start streaming — build and start pipeline
            self._start_pipeline()
            headers = {"Session": self._session_id}
            return build_response(RTSP_OK, request.cseq, headers=headers)

        elif request.method == RTSPMethod.TEARDOWN:
            # M7: Stop streaming
            self._stop_pipeline_and_emit()
            headers = {"Session": self._session_id}
            return build_response(RTSP_OK, request.cseq, headers=headers)

        elif request.method == RTSPMethod.PAUSE:
            if self._pipeline:
                self._pipeline.set_state(Gst.State.PAUSED)
            return build_response(RTSP_OK, request.cseq)

        else:
            return build_response(RTSP_BAD_REQUEST, request.cseq)

    def _start_pipeline(self) -> None:
        """Build and start the GStreamer pipeline."""
        try:
            video_codec = self._wfd_params.video_codec if self._wfd_params else "H264"
            audio_codec = self._wfd_params.audio_codec if self._wfd_params else "AAC"

            self._pipeline = self._pipeline_builder.build_pipeline(
                rtp_port=self._rtp_port,
                video_codec=video_codec,
                audio_codec=audio_codec if self._audio_enabled else "AAC",
                audio_enabled=self._audio_enabled,
                use_hw_decode=self._use_hw_decode,
            )

            # Set up bus message handling
            bus = self._pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect("message", self._on_bus_message)

            # Start playing
            ret = self._pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError("Pipeline failed to transition to PLAYING")

            # Wait for state change with timeout
            state_change = self._pipeline.get_state(_PIPELINE_STATE_TIMEOUT_SECONDS * Gst.SECOND)
            if state_change[0] == Gst.StateChangeReturn.FAILURE:
                if self._use_hw_decode:
                    logger.warning("Pipeline failed with HW decode, falling back to software")
                    self._use_hw_decode = False
                    self._pipeline.set_state(Gst.State.NULL)
                    self._pipeline = None
                    self._start_pipeline()
                    return
                raise RuntimeError("Pipeline failed to reach PLAYING state")

            self._last_rtp_time = time.monotonic()
            logger.info("GStreamer pipeline started on port %d", self._rtp_port)

            # Start stats monitoring thread
            self._stats_thread = threading.Thread(
                target=self._stats_monitor_loop,
                name="stats-monitor",
                daemon=True,
            )
            self._stats_thread.start()

            GLib.idle_add(self.emit, "stream-started")

        except Exception as e:
            error_msg = f"Failed to start pipeline: {e}"
            logger.error(error_msg)
            self._errors += 1
            GLib.idle_add(self.emit, "stream-error", error_msg)

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
        """Stats collection thread running at 1-second intervals.

        Monitors stream health, collects bitrate/resolution/frame stats,
        tracks peak bitrate, and detects stream loss.
        """
        last_bytes = 0
        frame_history: list[tuple[float, int, int]] = []  # (time, decoded, dropped)

        while self._running and self._pipeline:
            time.sleep(_STATS_INTERVAL_SECONDS)

            if not self._running or not self._pipeline:
                break

            now = time.monotonic()

            # Query pipeline position for stats
            try:
                # Get bytes received from udpsrc
                udpsrc = self._pipeline.get_by_name("udpsrc")
                if udpsrc:
                    # Query bytes-served or similar stat
                    pass  # GStreamer doesn't expose this directly; use position

                # Calculate bitrate from data received
                current_bytes = self._data_received
                bytes_delta = current_bytes - last_bytes
                bitrate = bytes_delta * 8.0  # bits per second (1s interval)
                last_bytes = current_bytes

                self._current_bitrate = bitrate
                if bitrate > self._peak_bitrate:
                    self._peak_bitrate = bitrate

                # Track frame stats for drop rate monitoring
                frame_history.append((now, self._frames_decoded, self._frames_dropped))

                # Keep only last 10 seconds of history
                cutoff = now - _FRAME_DROP_WINDOW_SECONDS
                frame_history = [(t, d, dr) for t, d, dr in frame_history if t >= cutoff]

                # Check frame drop rate over window
                if len(frame_history) >= 2:
                    first = frame_history[0]
                    last_entry = frame_history[-1]
                    decoded_delta = last_entry[1] - first[1]
                    dropped_delta = last_entry[2] - first[2]
                    if decoded_delta > 0:
                        drop_rate = dropped_delta / (decoded_delta + dropped_delta)
                        if drop_rate > _FRAME_DROP_WARNING_THRESHOLD:
                            logger.warning(
                                "Frame drop rate %.1f%% exceeds threshold (%.0f%%)",
                                drop_rate * 100,
                                _FRAME_DROP_WARNING_THRESHOLD * 100,
                            )

                # Check for stream loss (no RTP packets for 5 seconds)
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

                # Emit stats update
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

        Called by the pipeline probe or external monitor to update
        stream health tracking.

        Args:
            byte_count: Number of bytes received.
        """
        self._data_received += byte_count
        self._last_rtp_time = time.monotonic()
