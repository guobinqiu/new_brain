from services.ops.app.docker_engine import _decode_log_stream


def _frame(stream_type: int, payload: bytes) -> bytes:
    return bytes([stream_type, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload


def test_decode_docker_service_log_stream_removes_multiplex_headers():
    content = _frame(1, b"stdout line\n") + _frame(2, b"stderr line\n")

    assert _decode_log_stream(content) == "stdout line\nstderr line\n"


def test_decode_docker_service_log_stream_keeps_plain_text():
    assert _decode_log_stream(b"plain line\n") == "plain line\n"
