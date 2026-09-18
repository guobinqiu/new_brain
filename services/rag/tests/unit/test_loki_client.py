import pytest


pytestmark = pytest.mark.unit


def test_swarm_task_names_share_one_service_filter():
    from services.rag.core.loki_client import container_service, log_query

    tasks = ["brain_rag.1." + "a" * 25, "brain_rag.2." + "b" * 25, "brain-postgres"]
    assert sorted({container_service(name) for name in tasks}) == ["brain-postgres", "brain_rag"]
    assert log_query(container="brain_rag", include_tasks=True) == r'{container=~"brain_rag(\\.[0-9]+\\.[a-z0-9]{25})?"}'


def test_loki_log_query_escapes_labels():
    from services.rag.core.loki_client import log_query, trace_query

    assert log_query() == r'{container=~".+"}'
    assert log_query(node_id='node"1', container=r"rag\api") == r'{node_id="node\"1",container="rag\\api"}'
    assert trace_query(app_id="imsdom") == r'{container=~".+"} |= "search_trace" | json | app_id="imsdom"'


def test_loki_parse_logs_returns_rows_in_time_order():
    from services.rag.core.loki_client import parse_logs

    rows = parse_logs([
        {"stream": {"node_id": "node-1", "container": "rag"}, "values": [
            ["2000000000", '{"level":"INFO","message":"second"}'],
            ["1000000000", "plain"],
        ]},
    ])

    assert [row["line"] for row in rows] == ["plain", '{"level":"INFO","message":"second"}']
    assert rows[0]["parsed"] is None
    assert rows[0]["node_id"] == "node-1"
    assert rows[0]["container"] == "rag"
    assert rows[1]["parsed"]["message"] == "second"


def test_loki_parse_traces_filters_by_app_id_and_sorts_asc():
    from services.rag.core.loki_client import parse_traces

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
    from services.rag.core.loki_client import timestamp_to_ns

    assert timestamp_to_ns("1797422400123", 0) == "1797422400123000000"
    assert timestamp_to_ns("1797422400123000000", 0) == "1797422400123000000"
