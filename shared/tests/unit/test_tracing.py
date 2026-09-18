from shared.tracing import ensure_traceparent, reset_traceparent, set_traceparent, trace_headers, trace_id_from_traceparent


def test_traceparent_context_round_trips_headers():
    traceparent = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
    token = set_traceparent(traceparent)
    try:
        assert trace_headers() == {"traceparent": traceparent}
        assert trace_id_from_traceparent(traceparent) == "0123456789abcdef0123456789abcdef"
    finally:
        reset_traceparent(token)


def test_ensure_traceparent_creates_w3c_header():
    traceparent = ensure_traceparent()

    assert traceparent.startswith("00-")
    assert len(traceparent.split("-")) == 4
