import asyncio
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from services.parser.app.main import app, parse_file, upstream_exception_handler
from services.parser.common.schema import TextBlock
from services.parser.service import ParserService
from shared.config import ParserConfig
from shared.upstream import UpstreamServiceError


@pytest.mark.parametrize("failure", [RuntimeError, ValueError, TypeError, KeyError, OSError])
def test_local_parser_failure_is_normalized_and_cleans_upload(monkeypatch, failure):
    paths = []

    def fail(path, **kwargs):
        paths.append(Path(path))
        raise failure("private-document private-key")

    monkeypatch.setattr(app.state, "parser_service", SimpleNamespace(parse_file=fail), raising=False)
    upload = UploadFile(filename="private-document.txt", file=BytesIO(b"private-document"))
    with pytest.raises(UpstreamServiceError) as caught:
        parse_file(upload)
    error = caught.value
    assert error.service == "parser"
    assert error.status_code == 502
    assert error.retryable is False
    assert error.error == str(failure("private-document private-key"))
    assert upload.file.closed
    assert len(paths) == 1 and not paths[0].exists()
    response = asyncio.run(upstream_exception_handler(None, error))
    assert response.status_code == 502
    assert json.loads(response.body) == error.detail()


@pytest.mark.parametrize("blocks", [None, [object()], [TextBlock(text={"private-key": "private-document"})]])
def test_invalid_local_blocks_are_upstream_errors(monkeypatch, blocks):
    monkeypatch.setattr(app.state, "parser_service", SimpleNamespace(parse_file=lambda *args, **kwargs: blocks), raising=False)
    with pytest.raises(UpstreamServiceError) as caught:
        parse_file(UploadFile(filename="a.txt", file=BytesIO(b"private-document")))
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
def test_invalid_files_are_safe_400(monkeypatch, filename, content):
    monkeypatch.setattr(app.state, "parser_service", ParserService(ParserConfig()), raising=False)
    upload = UploadFile(filename=filename, file=BytesIO(content))
    with pytest.raises(HTTPException) as caught:
        parse_file(upload)
    assert caught.value.status_code == 400
    assert caught.value.detail
    assert upload.file.closed


def test_existing_upstream_error_is_preserved(monkeypatch):
    error = UpstreamServiceError(service="parser", error="parser request timed out", retryable=True, status_code=504)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(app.state, "parser_service", SimpleNamespace(parse_file=fail), raising=False)
    with pytest.raises(UpstreamServiceError) as caught:
        parse_file(UploadFile(filename="a.txt", file=BytesIO(b"text")))
    assert caught.value is error
