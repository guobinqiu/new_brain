import pytest


pytestmark = pytest.mark.unit


def test_loki_log_query_escapes_labels():
    from loki_client import log_query

    assert log_query(node_id='node"1', container=r"rag\backend") == r'{node_id="node\"1",container="rag\\backend"}'


def test_loki_parse_logs_returns_rows_in_time_order():
    from loki_client import parse_logs

    rows = parse_logs([
        {"values": [
            ["2000000000", '{"level":"INFO","message":"second"}'],
            ["1000000000", "plain"],
        ]},
    ])

    assert [row["line"] for row in rows] == ["plain", '{"level":"INFO","message":"second"}']
    assert rows[0]["parsed"] is None
    assert rows[1]["parsed"]["message"] == "second"


def test_loki_parse_traces_filters_by_app_id_and_sorts_desc():
    from loki_client import parse_traces

    rows = parse_traces([
        {"values": [
            ["1000000000", '{"event":"search_trace","app_id":"a","query":"old","elapsed_ms":1}'],
            ["3000000000", '{"event":"search_trace","app_id":"b","query":"skip","elapsed_ms":3}'],
            ["2000000000", '{"event":"search_trace","app_id":"a","query":"new","elapsed_ms":2}'],
        ]},
    ], app_id="a")

    assert [row["query"] for row in rows] == ["new", "old"]
    assert rows[0]["created_at"]
