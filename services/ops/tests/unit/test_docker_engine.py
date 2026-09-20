from services.ops.app.docker_engine import DockerLogStreamDecoder, _decode_log_stream


def _frame(stream_type: int, payload: bytes) -> bytes:
    return bytes([stream_type, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload


def test_decode_docker_service_log_stream_removes_multiplex_headers():
    content = _frame(1, b"stdout line\n") + _frame(2, b"stderr line\n")

    assert _decode_log_stream(content) == "stdout line\nstderr line\n"


def test_decode_docker_service_log_stream_keeps_plain_text():
    assert _decode_log_stream(b"plain line\n") == "plain line\n"


def test_stream_decoder_handles_headers_and_payloads_split_across_chunks():
    decoder = DockerLogStreamDecoder()
    content = _frame(1, b"stdout line\n") + _frame(2, b"stderr line\n")

    chunks = [content[:3], content[3:11], content[11:25], content[25:]]
    decoded = [text for chunk in chunks for text in decoder.feed(chunk)]
    decoded.extend(decoder.flush())

    assert decoded == ["stdout line\n", "stderr line\n"]


def test_stream_decoder_handles_plain_text_split_across_chunks():
    decoder = DockerLogStreamDecoder()

    decoded = decoder.feed(b"plain ") + decoder.feed(b"line\n") + decoder.flush()

    assert decoded == ["plain line\n"]
