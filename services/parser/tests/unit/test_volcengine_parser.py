import base64
import json

import httpx
import pytest

from services.parser.common.schema import FormulaBlock, TableBlock, TextBlock


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("actual_tier", ["fast", "default", None])
def test_stream_switch_and_timings(tmp_path, caplog, monkeypatch, stream, actual_tier):
    import services.parser.providers.volcengine.pdf as module
    from services.parser.providers.volcengine import VolcengineDocumentParser
    from shared.config import RetryConfig, VolcengineParserConfig

    clock = [0.0]
    monkeypatch.setattr(module.time, "perf_counter", lambda: clock[0])
    body = {"status": "completed", "usage": {"input_tokens": 10, "output_tokens": 5}, "output": [
        {"type": "message", "content": [{"type": "output_text", "text": '{"blocks":[{"type":"text","text":"hello"}]}'}]},
    ]}
    if actual_tier is not None:
        body["service_tier"] = actual_tier
    def handler(request):
        assert json.loads(request.content)["stream"] is stream
        assert json.loads(request.content)["service_tier"] == "fast"
        if not stream:
            return httpx.Response(200, json=body)
        events = [
            {"type": "response.created", "response": {"status": "in_progress"}},
            {"type": "response.output_text.delta", "delta": "hello"},
            {"type": "response.completed", "response": body},
        ]
        class Stream(httpx.SyncByteStream):
            def __iter__(self):
                for timestamp, event in zip([1.0, 5.0, 11.0], events):
                    clock[0] = timestamp
                    yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()

        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Stream())

    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.7 test")
    with caplog.at_level("INFO", logger="services.parser.providers.volcengine"):
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            parser = VolcengineDocumentParser(VolcengineParserConfig(base_url="https://ark.example/api/v3", stream=stream, service_tier="fast"), http_client=http)
            assert parser.parse_file(str(path)) == [TextBlock("hello")]
    record = next(row for row in caplog.records if row.name == "services.parser.providers.volcengine")
    assert record.stream is stream
    assert record.requested_service_tier == "fast"
    assert record.service_tier == actual_tier
    assert record.input_tokens == 10
    assert record.first_text_ms == (5000.0 if stream else None)
    assert record.output_ms == (6000.0 if stream else None)


@pytest.mark.parametrize("failure", ["timeout", "http_error"])
def test_stream_transport_failure_closes_response(tmp_path, caplog, failure):
    from services.parser.providers.volcengine import VolcengineDocumentParser
    from shared.config import RetryConfig, VolcengineParserConfig
    from shared.upstream import UpstreamServiceError

    class Stream(httpx.SyncByteStream):
        closed = False

        def __iter__(self):
            if failure == "http_error":
                yield b'{"error":{"code":"ServerOverloaded","message":"busy"}}'
            else:
                yield b'data: {"type":"response.output_text.delta","delta":"partial"}\n\n'
                raise httpx.ReadTimeout("read timeout")

        def close(self):
            self.closed = True

    stream = Stream()
    response = httpx.Response(500 if failure == "http_error" else 200, headers={"content-type": "text/event-stream"}, stream=stream)
    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.7 test")
    config = VolcengineParserConfig(base_url="https://ark.example/api/v3", stream=True, retry=RetryConfig(max_attempts=1))
    with httpx.Client(transport=httpx.MockTransport(lambda request: response)) as http:
        parser = VolcengineDocumentParser(config, http_client=http)
        with pytest.raises(UpstreamServiceError) as caught:
            parser.parse_file(str(path))
    assert caught.value.retryable is True
    assert caught.value.error == ("busy" if failure == "http_error" else "read timeout")
    assert stream.closed
    record = next(row for row in caplog.records if row.name == "services.parser.providers.volcengine")
    assert record.output_ms is None


def test_retryable_volcengine_failure_is_retried(tmp_path, monkeypatch):
    from services.parser.providers.volcengine import VolcengineDocumentParser
    from shared.config import RetryConfig, VolcengineParserConfig

    monkeypatch.setattr("shared.retry.time.sleep", lambda seconds: None)
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(500, json={"error": {
                "code": "InternalServiceError", "message": "busy",
            }})
        return httpx.Response(200, json={"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": '{"blocks":[{"type":"text","text":"ok"}]}'}]},
        ]})

    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.7 test")
    config = VolcengineParserConfig(
        base_url="https://ark.example/api/v3",
        retry=RetryConfig(max_attempts=3, interval_seconds=0.5),
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        parser = VolcengineDocumentParser(config, http_client=http)
        assert parser.parse_file(str(path)) == [TextBlock("ok")]
    assert len(calls) == 2


@pytest.mark.parametrize("payload", [
    'data: {"type":"response.output_text.delta","delta":"partial"}\n\n',
    'data: {"type":"response.failed","response":{"status":"failed","output":[]}}\n\n',
    'data: {"type":"error","message":"provider failed"}\n\n',
    'data: invalid json\n\n',
])
def test_stream_failure_does_not_return_partial_blocks(tmp_path, payload):
    from services.parser.providers.volcengine import VolcengineDocumentParser
    from shared.config import RetryConfig, VolcengineParserConfig
    from shared.upstream import UpstreamServiceError

    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.7 test")
    response = httpx.Response(200, headers={"content-type": "text/event-stream"}, content=payload)
    with httpx.Client(transport=httpx.MockTransport(lambda request: response)) as http:
        parser = VolcengineDocumentParser(VolcengineParserConfig(base_url="https://ark.example/api/v3", stream=True), http_client=http)
        with pytest.raises(UpstreamServiceError):
            parser.parse_file(str(path))
    assert response.is_closed


@pytest.mark.parametrize("thinking", [None, False, True])
def test_pdf_request_and_normalized_blocks(tmp_path, thinking):
    from services.parser.providers.volcengine import VolcengineDocumentParser
    from shared.config import VolcengineParserConfig

    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.7 test")

    def handler(request):
        assert str(request.url) == "https://ark.example/api/v3/responses"
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "test-model"
        assert payload["thinking"] == {"type": "enabled" if thinking else "disabled"}
        assert payload["input"][0]["content"][1] == {"type": "input_text", "text": "Extract all blocks"}
        file = payload["input"][0]["content"][0]
        assert file["filename"] == "report.pdf"
        assert file["type"] == "input_file"
        assert base64.b64decode(file["file_data"].split(",", 1)[1]) == path.read_bytes()
        return httpx.Response(200, json={"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps({"blocks": [
                {"type": "text", "text": "Introduction", "page": 1},
                {"type": "table", "rows": [["Name"], ["A"]]},
                {"type": "formula", "text": "x^2", "format": "latex"},
            ]})}]},
        ]})

    options = {} if thinking is None else {"thinking": thinking}
    config = VolcengineParserConfig(base_url="https://ark.example/api/v3", model="test-model", prompt="Extract all blocks", api_key="test-key", **options)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        parser = VolcengineDocumentParser(config, http_client=http)
        assert parser.parse_file(str(path)) == [TextBlock("Introduction", page=1), TableBlock(rows=[["Name"], ["A"]]), FormulaBlock("x^2")]


@pytest.mark.parametrize("status", ["completed", "incomplete"])
@pytest.mark.parametrize("metrics", [
    {"thinking": {"type": "enabled"}, "usage": {"input_tokens": 100, "output_tokens": 80, "total_tokens": 180, "output_tokens_details": {"reasoning_tokens": 30}}},
    {"thinking": {"type": "disabled"}, "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150, "output_tokens_details": {"reasoning_tokens": 0}}},
    {},
    {"thinking": None, "usage": None},
])
def test_logs_response_usage_and_thinking(tmp_path, caplog, status, metrics):
    from services.parser.providers.volcengine import VolcengineDocumentParser
    from shared.config import VolcengineParserConfig
    from shared.upstream import UpstreamServiceError

    body = {"status": status, "output": [{"type": "message", "content": [
        {"type": "output_text", "text": '{"blocks":[{"type":"text","text":"hello"}]}'},
    ]}], **metrics}
    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.7 test")
    with caplog.at_level("INFO", logger="services.parser.providers.volcengine"):
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as http:
            parser = VolcengineDocumentParser(VolcengineParserConfig(base_url="https://ark.example/api/v3"), http_client=http)
            if status == "completed":
                assert parser.parse_file(str(path)) == [TextBlock("hello")]
            else:
                with pytest.raises(UpstreamServiceError):
                    parser.parse_file(str(path))
    record = next(row for row in caplog.records if row.name == "services.parser.providers.volcengine")
    usage = metrics.get("usage") or {}
    assert record.input_tokens == usage.get("input_tokens")
    assert record.output_tokens == usage.get("output_tokens")
    assert record.total_tokens == usage.get("total_tokens")
    assert record.reasoning_tokens == usage.get("output_tokens_details", {}).get("reasoning_tokens")
    assert record.thinking == (metrics.get("thinking") or {}).get("type")


def test_incomplete_output_is_not_indexed(tmp_path):
    from services.parser.providers.volcengine import VolcengineDocumentParser
    from shared.config import VolcengineParserConfig

    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.7 test")
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        "status": "incomplete", "output": [],
    }))) as http:
        parser = VolcengineDocumentParser(VolcengineParserConfig(base_url="https://ark.example/api/v3"), http_client=http)
        from shared.upstream import UpstreamServiceError

        with pytest.raises(UpstreamServiceError, match="incomplete"):
            parser.parse_file(str(path))


@pytest.mark.parametrize("body", [
    b"private-document-not-json", b"null", b"[]", b"{}",
    b'{"status":"completed"}',
    b'{"status":"completed","output":null}',
    b'{"status":"completed","output":[null]}',
    b'{"status":"completed","output":[{"type":"message","content":null}]}',
    *[json.dumps({"status": "completed", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": output},
    ]}]}).encode() for output in [
        None, "private-document-not-json", "null", "{}",
        '{"blocks":[{"type":"text"}]}',
        '{"blocks":[{"type":"text","text":{"private-key":"private-document"}}]}',
        '{"blocks":[{"type":"table","rows":"private-document"}]}',
    ]],
    b'{"status":"incomplete","output":[],"private-key":"private-document"}',
])
def test_invalid_response_is_safe_non_retryable_error(tmp_path, body):
    from services.parser.providers.volcengine import VolcengineDocumentParser
    from shared.config import VolcengineParserConfig
    from shared.upstream import UpstreamServiceError

    path = tmp_path / "report.pdf"
    path.write_bytes(b"private-document")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        parser = VolcengineDocumentParser(VolcengineParserConfig(base_url="https://ark.example/api/v3", api_key="private-key"), http_client=http)
        with pytest.raises(UpstreamServiceError) as caught:
            parser.parse_file(str(path))
    error = caught.value
    assert error.service == "parser"
    assert error.status_code == 502
    assert error.retryable is False
    assert isinstance(error.error, str)
    assert error.error
    assert len(calls) == 1


@pytest.mark.parametrize("outcome", ["success", "invalid", "incomplete", "structured_error", "structured_redirect", 401, 402, 403, 429, 500, "timeout"])
@pytest.mark.parametrize("request_id", [None, "provider-real-id"])
def test_external_call_logs_safe_context(tmp_path, caplog, outcome, request_id):
    from services.parser.providers.volcengine import VolcengineDocumentParser
    from shared.config import RetryConfig, VolcengineParserConfig
    from shared.tracing import reset_traceparent, set_traceparent
    from shared.upstream import UpstreamServiceError, upstream_error

    calls = []
    source = []

    def handler(request):
        calls.append(request)
        if outcome == "timeout":
            error = httpx.ReadTimeout("private-document private-key", request=request)
            source.append(error)
            raise error
        headers = {"x-request-id": request_id} if request_id is not None else {}
        body = {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": '{"blocks":[{"type":"text","text":"private-document"}]}'},
        ]}]}
        if outcome == "incomplete":
            body["status"] = "incomplete"
        if outcome in ("structured_error", "structured_redirect"):
            return httpx.Response(302 if outcome == "structured_redirect" else 402, headers=headers, json={
                "service": "parser", "code": "private-key", "message": "private-document", "retryable": False,
            })
        response = httpx.Response(outcome if isinstance(outcome, int) else 200, headers=headers,
                                  json=body if outcome in ("success", "incomplete") else {"private-key": "private-document"})
        if isinstance(outcome, int):
            source.append(httpx.HTTPStatusError("private-document", request=request, response=response))
        return response

    path = tmp_path / "private-document.pdf"
    path.write_bytes(b"private-document")
    token = set_traceparent("00-" + "a" * 32 + "-" + "b" * 16 + "-01")
    try:
        with caplog.at_level("INFO", logger="services.parser.providers.volcengine"):
            with httpx.Client(transport=httpx.MockTransport(handler)) as http:
                config = VolcengineParserConfig(base_url="https://ark.example/api/v3", api_key="private-key", retry=RetryConfig(max_attempts=1))
                parser = VolcengineDocumentParser(config, http_client=http)
                if outcome == "success":
                    assert parser.parse_file(str(path)) == [TextBlock("private-document")]
                else:
                    with pytest.raises(UpstreamServiceError) as caught:
                        parser.parse_file(str(path))
                    if source:
                        expected = upstream_error("parser", source[0], retryable=outcome == 500)
                        assert caught.value.detail() == expected.detail()
                        assert caught.value.status_code == expected.status_code
    finally:
        reset_traceparent(token)
    records = [row for row in caplog.records if row.name == "services.parser.providers.volcengine"]
    assert len(records) == 1 and len(calls) == 1
    record = records[0]
    assert record.trace_id == "a" * 32
    assert record.elapsed_ms >= 0
    expected_status = {"timeout": None, "structured_error": 402, "structured_redirect": 302}.get(outcome, outcome if isinstance(outcome, int) else 200)
    assert record.status_code == expected_status
    assert record.provider_request_id == (None if outcome == "timeout" else request_id)
    assert record.levelname == ("INFO" if outcome == "success" else "ERROR")
    assert record.error == (None if outcome == "success" else caught.value.error)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("thinking", [False, True])
def test_volcengine_selection_and_document_routing(tmp_path, monkeypatch, thinking, stream):
    from services.parser.app.config import load_parser_config
    from services.parser.service import ParserService
    from services.parser.providers.volcengine import VolcengineDocumentParser

    monkeypatch.setenv("ARK_API_KEY", "test-key")
    monkeypatch.setenv("ARK_TIMEOUT", "1")
    config_path = tmp_path / "parser.yaml"
    config_path.write_text(f"parser:\n  volcengine:\n    enable: true\n    base_url: https://ark.example/api/v3\n    timeout: 240\n    retry:\n      max_attempts: 3\n      interval_seconds: 0.5\n    model: test-model\n    thinking: {str(thinking).lower()}\n    stream: {str(stream).lower()}\n    service_tier: fast\n    prompt: Extract all blocks\n", encoding="utf-8")
    config = load_parser_config(config_path)
    assert config.volcengine.timeout == 240
    assert config.volcengine.retry.max_attempts == 3
    assert config.volcengine.retry.interval_seconds == 0.5
    assert config.volcengine.base_url == "https://ark.example/api/v3"
    assert config.volcengine.thinking is thinking
    assert config.volcengine.stream is stream
    assert config.volcengine.service_tier == "fast"
    assert config.active == "volcengine"
    assert config.volcengine.prompt == "Extract all blocks"
    assert config.volcengine.api_key == "test-key"
    service = ParserService(config)
    assert isinstance(service.pdf_parser, VolcengineDocumentParser)
    for extension, content in [("txt", "First paragraph"), ("md", "# Title")]:
        path = tmp_path / f"document.{extension}"
        path.write_text(content, encoding="utf-8")
        assert service.parse_file(str(path))


def test_pdf_list_fragments_merge_without_crossing_structural_boundaries(tmp_path):
    from services.parser.providers.volcengine import VolcengineDocumentParser
    from shared.config import VolcengineParserConfig

    lines = ["6. FAISS", "优点：", "算法最全：包含主流向量索引算法", "性能基准：极度优化", "缺点：", "非独立服务：没有网络接口"]
    blocks = [{"type": "text", "text": text, "page": 1} for text in lines]
    blocks.extend([
        {"type": "table", "rows": [["库", "类型"], ["FAISS", "本地"]], "page": 1},
        {"type": "text", "text": "表后说明", "page": 1},
        {"type": "formula", "text": "x^2", "format": "latex", "page": 1},
        {"type": "text", "text": "公式说明", "page": 1},
        {"type": "text", "text": "下一页正文", "page": 2},
    ])
    response = {"status": "completed", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": json.dumps({"blocks": blocks})},
    ]}]}
    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.7 test")
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))) as http:
        parser = VolcengineDocumentParser(VolcengineParserConfig(base_url="https://ark.example/api/v3"), http_client=http)
        assert parser.parse_file(str(path)) == [
            TextBlock("\n".join(lines), page=1),
            TableBlock(rows=[["库", "类型"], ["FAISS", "本地"]], page=1),
            TextBlock("表后说明", page=1),
            FormulaBlock("x^2", page=1),
            TextBlock("公式说明", page=1),
            TextBlock("下一页正文", page=2),
        ]
def test_volcengine_preserves_all_text_kinds():
    from services.parser.providers.volcengine.normalizer import normalize_response_result

    kinds = ["heading", "paragraph", "list_item", "code", "text"]
    blocks = [{"type": "text", "kind": kind, "text": f"content {kind}", "page": 1} for kind in kinds]
    result = {"status": "completed", "output": [{
        "type": "message", "content": [{"type": "output_text", "text": json.dumps({"blocks": blocks})}],
    }]}
    assert [block.kind for block in normalize_response_result(result)] == kinds

