from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from services.parser.app.main import ParseFileRequest, ParseFileResponse, _block_response, app, health, parse_file, ready
from services.parser.common.schema import FormulaBlock, TableBlock, TextBlock
from services.parser.service import ParserService
from shared.config import ParserConfig


def test_parser_health_returns_ok():
    assert health() == {"status": "ok"}


def test_parser_ready_returns_503_until_service_is_ready(monkeypatch):
    monkeypatch.delattr(app.state, "parser_service", raising=False)
    with pytest.raises(HTTPException) as error:
        ready()
    assert error.value.status_code == 503


def test_parser_ready_returns_200_when_service_is_ready(monkeypatch):
    monkeypatch.setattr(app.state, "parser_service", SimpleNamespace(ready=True), raising=False)
    assert ready() == {"status": "ready"}


def test_parse_file_returns_blocks(monkeypatch):
    service = SimpleNamespace(parse_url=lambda *args, **kwargs: ([TextBlock("hello parser", kind="paragraph")], 12))
    monkeypatch.setattr(app.state, "parser_service", service, raising=False)

    response = parse_file(ParseFileRequest(presigned_url="https://source/sample.txt", filename="sample.txt"))

    assert response.model_dump(exclude_none=True) == {
        "blocks": [{"type": "text", "text": "hello parser", "kind": "paragraph"}],
        "file_size": 12,
    }


def test_response_serializes_each_block_type():
    blocks = [
        TextBlock("标题", page=1),
        TableBlock(rows=[["列"], ["值"]], caption="表格标题", page=1),
        TableBlock(rows=[["另一列"], ["另一值"]], caption="  "),
        FormulaBlock("E=mc^2", page=2),
        FormulaBlock("a+b"),
    ]

    response = ParseFileResponse(blocks=[_block_response(block) for block in blocks])

    assert response.model_dump(exclude_none=True) == {"blocks": [
        {"type": "text", "text": "标题", "kind": "text", "page": 1},
        {"type": "table", "rows": [["列"], ["值"]], "caption": "表格标题", "page": 1},
        {"type": "table", "rows": [["另一列"], ["另一值"]]},
        {"type": "formula", "text": "E=mc^2", "format": "latex", "page": 2},
        {"type": "formula", "text": "a+b", "format": "latex"},
    ]}
