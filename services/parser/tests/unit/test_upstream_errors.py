import asyncio
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from services.parser.app.main import ParseFileRequest, app, parse_file, upstream_exception_handler
from services.parser.common.schema import TextBlock
from services.parser.service import ParserService
from shared.config import ParserConfig
from shared.upstream import UpstreamServiceError


@pytest.mark.parametrize("failure", [RuntimeError, ValueError, TypeError, KeyError, OSError])
def test_parser_failure_is_normalized(monkeypatch, failure):
    paths = []

    def fail(path, **kwargs):
        paths.append(Path(path))
        raise failure("private-document private-key")

    monkeypatch.setattr(app.state, "parser_service", SimpleNamespace(parse_url=fail), raising=False)
    request = ParseFileRequest(filename="private-document.txt", presigned_url="https://source/private-document.txt")
    with pytest.raises(UpstreamServiceError) as caught:
        parse_file(request)
    error = caught.value
    assert error.service == "parser"
    assert error.status_code == 502
    assert error.retryable is False
    assert error.error == str(failure("private-document private-key"))
    response = asyncio.run(upstream_exception_handler(None, error))
    assert response.status_code == 502
    assert json.loads(response.body) == error.detail()


@pytest.mark.parametrize("blocks", [None, [object()], [TextBlock(text={"private-key": "private-document"})]])
def test_invalid_local_blocks_are_upstream_errors(monkeypatch, blocks):
    monkeypatch.setattr(app.state, "parser_service", SimpleNamespace(parse_url=lambda *args, **kwargs: (blocks, None)), raising=False)
    with pytest.raises(UpstreamServiceError) as caught:
        parse_file(ParseFileRequest(presigned_url="https://source/a.txt", filename="a.txt"))
    assert caught.value.status_code == 502
    assert caught.value.retryable is False
    assert caught.value.error


@pytest.mark.parametrize("filename, content", [
    ("private-name.exe", b"private-document"),
    ("private-name.pdf", b"private-document"),
    ("private-name.docx", b"private-document"),
    ("private-name.xlsx", b"private-document"),
    ("private-name.pptx", b"private-document"),
    ("private-name.txt", b""),
    ("private-name.txt", b"\xff"),
])
def test_invalid_local_files_fail(tmp_path, filename, content):
    path = tmp_path / filename
    path.write_bytes(content)
    with pytest.raises((ValueError, UnicodeDecodeError)):
        ParserService(ParserConfig()).parse_file(str(path), original_filename=filename)


def test_existing_upstream_error_is_preserved(monkeypatch):
    error = UpstreamServiceError(service="parser", error="parser request timed out", retryable=True, status_code=504)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(app.state, "parser_service", SimpleNamespace(parse_url=fail), raising=False)
    with pytest.raises(UpstreamServiceError) as caught:
        parse_file(ParseFileRequest(presigned_url="https://source/a.txt", filename="a.txt"))
    assert caught.value is error
