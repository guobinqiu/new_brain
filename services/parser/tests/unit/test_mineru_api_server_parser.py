import json

import httpx
import pytest

from services.parser.common.schema import TableBlock, TextBlock


pytestmark = pytest.mark.unit


def test_mineru_parser_uses_official_api_server_flow(tmp_path, monkeypatch):
    from services.parser.providers.mineru.api_parser import MineruApiServerDocumentParser
    from shared.config import MineruParserConfig, RetryConfig

    monkeypatch.setattr("services.parser.providers.mineru.api_parser.validate_pdf_file", lambda filepath: None)
    monkeypatch.setattr("services.parser.providers.mineru.api_server.POLL_INTERVAL_SECONDS", 0)
    calls = []

    def handler(request):
        calls.append((request.method, str(request.url), request.headers, request.content))
        if request.method == "POST" and str(request.url) == "http://mineru_api_server:8000/v1/uploads":
            body = json.loads(request.content)
            assert body["filename"] == "report.pdf"
            assert body["purpose"] == "parse"
            assert body["bytes"] == 13
            return httpx.Response(200, json={
                "id": "upload-1",
                "status": "pending",
                "upload_url": "/v1/uploads/upload-1/content",
                "upload_method": "PUT",
                "upload_headers": {"Content-Type": "application/pdf"},
            })
        if request.method == "PUT" and str(request.url) == "http://mineru_api_server:8000/v1/uploads/upload-1/content":
            assert request.content == b"%PDF-1.7 test"
            assert request.headers["content-type"] == "application/pdf"
            return httpx.Response(200)
        if request.method == "POST" and str(request.url) == "http://mineru_api_server:8000/v1/uploads/upload-1/complete":
            return httpx.Response(200, json={"status": "completed", "file": {"id": "file-1"}})
        if request.method == "POST" and str(request.url) == "http://mineru_api_server:8000/v1/parse/jobs":
            body = json.loads(request.content)
            assert body["files"] == [{"source": {"type": "file_id", "file_id": "file-1"}}]
            assert body["tier"] == "standard"
            assert body["output_formats"] == ["structured_content"]
            return httpx.Response(200, json={"job_id": "job-1", "status": "running"})
        if request.method == "GET" and str(request.url) == "http://mineru_api_server:8000/v1/parse/jobs/job-1":
            return httpx.Response(200, json={
                "job_id": "job-1",
                "status": "completed",
                "files": [{
                    "name": "report.pdf",
                    "status": "completed",
                    "output_files": {"structured_content": {"file_id": "content-1"}},
                }],
            })
        if request.method == "GET" and str(request.url) == "http://mineru_api_server:8000/v1/files/content-1/content":
            return httpx.Response(200, json=[
                {"type": "text", "text": "标题", "text_level": 1, "page_idx": 0},
                {"type": "table", "rows": [["Name", "Value"], ["Milvus", "向量库"]], "page_idx": 1},
            ])
        return httpx.Response(404, json={"error": str(request.url)})

    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.7 test")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        parser = MineruApiServerDocumentParser(
            MineruParserConfig(
                base_url="http://mineru_api_server:8000",
                tier="standard",
                retry=RetryConfig(max_attempts=1),
            ),
            http_client=http,
        )
        assert parser.parse_file(str(path), original_filename="report.pdf") == [
            TextBlock("标题", page=1, kind="heading"),
            TableBlock(rows=[["Name", "Value"], ["Milvus", "向量库"]], page=2),
        ]

    assert [call[0] for call in calls] == ["POST", "PUT", "POST", "POST", "GET", "GET"]


def test_mineru_parser_reports_failed_api_server_job(tmp_path, monkeypatch):
    from services.parser.providers.mineru.api_parser import MineruApiServerDocumentParser
    from shared.config import MineruParserConfig, RetryConfig
    from shared.upstream import UpstreamServiceError

    monkeypatch.setattr("services.parser.providers.mineru.api_parser.validate_pdf_file", lambda filepath: None)
    monkeypatch.setattr("services.parser.providers.mineru.api_server.time.sleep", lambda seconds: None)

    def handler(request):
        if str(request.url) == "http://mineru_api_server:8000/v1/uploads":
            return httpx.Response(200, json={"id": "upload-1", "status": "completed", "file": {"id": "file-1"}})
        if str(request.url) == "http://mineru_api_server:8000/v1/parse/jobs":
            return httpx.Response(200, json={"job_id": "job-1", "status": "failed", "files": [{
                "name": "report.pdf",
                "status": "failed",
                "error": {"code": "PARSE_FAILED", "message": "bad pdf"},
            }]})
        return httpx.Response(404)

    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.7 test")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        parser = MineruApiServerDocumentParser(
            MineruParserConfig(base_url="http://mineru_api_server:8000", retry=RetryConfig(max_attempts=1)),
            http_client=http,
        )
        with pytest.raises(UpstreamServiceError) as caught:
            parser.parse_file(str(path), original_filename="report.pdf")

    assert caught.value.error == "bad pdf"
    assert caught.value.retryable is False
