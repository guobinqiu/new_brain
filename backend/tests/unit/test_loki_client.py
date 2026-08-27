import pytest


pytestmark = pytest.mark.unit


def test_loki_log_query_escapes_labels():
    from loki_client import log_query, trace_query

    assert log_query(node_id='node"1', container=r"rag\backend") == r'{node_id="node\"1",container="rag\\backend"}'
    assert trace_query(app_id="imsdom") == r'{container="rag-backend"} |= "search_trace" | json | app_id="imsdom"'


def test_loki_parse_logs_returns_rows_in_time_order():
    from loki_client import parse_logs

    rows = parse_logs([
        {"stream": {"node_id": "node-1", "container": "rag-backend"}, "values": [
            ["2000000000", '{"level":"INFO","message":"second"}'],
            ["1000000000", "plain"],
        ]},
    ])

    assert [row["line"] for row in rows] == ["plain", '{"level":"INFO","message":"second"}']
    assert rows[0]["parsed"] is None
    assert rows[0]["node_id"] == "node-1"
    assert rows[0]["container"] == "rag-backend"
    assert rows[1]["parsed"]["message"] == "second"


def test_loki_parse_traces_filters_by_app_id_and_sorts_asc():
    from loki_client import parse_traces

    rows = parse_traces([
        {"values": [
            ["1000000000", '{"event":"search_trace","app_id":"a","query":"old","elapsed_ms":1}'],
            ["3000000000", '{"event":"search_trace","app_id":"b","query":"skip","elapsed_ms":3}'],
            ["2000000000", '{"event":"search_trace","app_id":"a","query":"new","elapsed_ms":2}'],
        ]},
    ], app_id="a")

    assert [row["query"] for row in rows] == ["old", "new"]
    assert rows[0]["created_at"]


def test_loki_timestamp_to_ns_accepts_ui_milliseconds():
    from loki_client import timestamp_to_ns

    assert timestamp_to_ns("1797422400123", 0) == "1797422400123000000"
    assert timestamp_to_ns("1797422400123000000", 0) == "1797422400123000000"
