"""Tests for RTSP message parsing and generation."""

import pytest

from miracast_server.rtsp import (
    RTSPMethod,
    RTSPParseError,
    RTSPRequest,
    RTSPResponse,
    WFDParameters,
    build_capability_response_body,
    build_options_response,
    build_response,
    parse_rtsp_request,
    parse_wfd_parameters,
    validate_request_size,
    RTSP_OK,
    RTSP_BAD_REQUEST,
    _MAX_HEADER_SIZE,
    _MAX_BODY_SIZE,
)


class TestRTSPRequestParsing:
    """Test RTSP request parser."""

    def test_parse_options_request(self):
        data = b"OPTIONS * RTSP/1.0\r\nCSeq: 1\r\n\r\n"
        req = parse_rtsp_request(data)
        assert req.method == RTSPMethod.OPTIONS
        assert req.uri == "*"
        assert req.cseq == 1

    def test_parse_set_parameter_with_body(self):
        data = (
            b"SET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0\r\n"
            b"CSeq: 3\r\n"
            b"Content-Length: 30\r\n"
            b"\r\n"
            b"wfd_video_formats: 00 00 02 10"
        )
        req = parse_rtsp_request(data)
        assert req.method == RTSPMethod.SET_PARAMETER
        assert req.cseq == 3
        assert "wfd_video_formats" in req.body

    def test_parse_setup_request(self):
        data = (
            b"SETUP rtsp://192.168.49.1/wfd1.0/streamid=0 RTSP/1.0\r\n"
            b"CSeq: 4\r\n"
            b"Transport: RTP/AVP/UDP;unicast;client_port=1028\r\n"
            b"\r\n"
        )
        req = parse_rtsp_request(data)
        assert req.method == RTSPMethod.SETUP
        assert req.cseq == 4
        assert "Transport" in req.headers

    def test_parse_play_request(self):
        data = b"PLAY rtsp://192.168.49.1/wfd1.0 RTSP/1.0\r\nCSeq: 5\r\nSession: ABC123\r\n\r\n"
        req = parse_rtsp_request(data)
        assert req.method == RTSPMethod.PLAY
        assert req.cseq == 5
        assert req.headers["Session"] == "ABC123"

    def test_parse_teardown_request(self):
        data = b"TEARDOWN rtsp://192.168.49.1/wfd1.0 RTSP/1.0\r\nCSeq: 7\r\nSession: ABC123\r\n\r\n"
        req = parse_rtsp_request(data)
        assert req.method == RTSPMethod.TEARDOWN
        assert req.cseq == 7

    def test_missing_cseq_raises(self):
        data = b"OPTIONS * RTSP/1.0\r\n\r\n"
        with pytest.raises(RTSPParseError, match="CSeq"):
            parse_rtsp_request(data)

    def test_empty_request_raises(self):
        with pytest.raises(RTSPParseError):
            parse_rtsp_request(b"")

    def test_malformed_request_line_raises(self):
        data = b"GARBAGE\r\nCSeq: 1\r\n\r\n"
        with pytest.raises(RTSPParseError):
            parse_rtsp_request(data)

    def test_unknown_method_raises(self):
        data = b"FOOBAR * RTSP/1.0\r\nCSeq: 1\r\n\r\n"
        with pytest.raises(RTSPParseError, match="Unknown method"):
            parse_rtsp_request(data)

    def test_invalid_cseq_raises(self):
        data = b"OPTIONS * RTSP/1.0\r\nCSeq: abc\r\n\r\n"
        with pytest.raises(RTSPParseError, match="Invalid CSeq"):
            parse_rtsp_request(data)

    def test_cseq_case_insensitive(self):
        data = b"OPTIONS * RTSP/1.0\r\ncseq: 42\r\n\r\n"
        req = parse_rtsp_request(data)
        assert req.cseq == 42


class TestRTSPResponseBuilding:
    """Test RTSP response serialization."""

    def test_build_ok_response(self):
        resp = build_response(200, cseq=1)
        data = resp.serialize()
        assert b"RTSP/1.0 200 OK" in data
        assert b"CSeq: 1" in data

    def test_response_echoes_cseq(self):
        """FR-RN12: CSeq must be echoed in response."""
        for cseq in [0, 1, 100, 2147483647]:
            resp = build_response(200, cseq=cseq)
            assert f"CSeq: {cseq}".encode() in resp.serialize()

    def test_options_response_includes_all_methods(self):
        """FR-RN02: Public header must list all supported methods."""
        resp = build_options_response(cseq=1)
        data = resp.serialize().decode()
        assert "GET_PARAMETER" in data
        assert "SET_PARAMETER" in data
        assert "SETUP" in data
        assert "PLAY" in data
        assert "TEARDOWN" in data

    def test_response_with_body(self):
        body = "wfd_content_protection: none"
        resp = build_response(200, cseq=2, body=body)
        data = resp.serialize()
        assert f"Content-Length: {len(body)}".encode() in data
        assert b"wfd_content_protection: none" in data


class TestRTSPSizeValidation:
    """Test request size limit enforcement (NFR-S05)."""

    def test_normal_size_passes(self):
        validate_request_size(b"x" * 1000)  # Should not raise

    def test_oversized_request_raises(self):
        oversized = b"x" * (_MAX_HEADER_SIZE + _MAX_BODY_SIZE + 1)
        with pytest.raises(RTSPParseError) as exc_info:
            validate_request_size(oversized)
        assert exc_info.value.status_code == 413


class TestWFDParameterParsing:
    """Test WFD SET_PARAMETER body parsing."""

    def test_parse_video_formats(self):
        body = "wfd_video_formats: 00 00 02 10 0001DEFF 00000000 00000000 00 0000 0000 00 none none"
        params = parse_wfd_parameters(body)
        assert params.video_codec == "H264"
        assert params.video_formats is not None
        assert params.video_formats.profile == 0x02

    def test_parse_audio_codecs(self):
        body = "wfd_audio_codecs: AAC 00000007 00"
        params = parse_wfd_parameters(body)
        assert params.audio_codec == "AAC"
        assert params.audio_codecs.modes_bitmap == 0x00000007

    def test_parse_rtp_ports(self):
        body = "wfd_client_rtp_ports: RTP/AVP/UDP;unicast 1028 0 mode=play"
        params = parse_wfd_parameters(body)
        assert params.rtp_port == 1028

    def test_parse_content_protection(self):
        body = "wfd_content_protection: none"
        params = parse_wfd_parameters(body)
        assert params.content_protection == "none"

    def test_parse_multiple_params(self):
        body = (
            "wfd_video_formats: 00 00 02 10 0001DEFF 00000000 00000000 00 0000 0000 00 none none\r\n"
            "wfd_audio_codecs: AAC 00000007 00\r\n"
            "wfd_client_rtp_ports: RTP/AVP/UDP;unicast 1028 0 mode=play\r\n"
            "wfd_content_protection: none"
        )
        params = parse_wfd_parameters(body)
        assert params.video_codec == "H264"
        assert params.audio_codec == "AAC"
        assert params.rtp_port == 1028
        assert params.content_protection == "none"

    def test_empty_body_returns_defaults(self):
        params = parse_wfd_parameters("")
        assert params.video_codec == ""
        assert params.rtp_port == 0


class TestCapabilityResponse:
    """Test WFD capability response generation (M3 response)."""

    def test_includes_video_formats(self):
        body = build_capability_response_body()
        assert "wfd_video_formats:" in body

    def test_includes_audio_codecs(self):
        body = build_capability_response_body()
        assert "wfd_audio_codecs:" in body
        assert "AAC" in body

    def test_includes_rtp_ports(self):
        body = build_capability_response_body(rtp_port=1028)
        assert "wfd_client_rtp_ports:" in body
        assert "1028" in body

    def test_includes_content_protection_none(self):
        body = build_capability_response_body()
        assert "wfd_content_protection: none" in body

    def test_includes_coupled_sink(self):
        body = build_capability_response_body()
        assert "wfd_coupled_sink: none" in body

    def test_custom_port(self):
        body = build_capability_response_body(rtp_port=5000)
        assert "5000" in body
