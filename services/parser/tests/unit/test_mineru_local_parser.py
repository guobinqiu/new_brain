import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from services.parser.app.config import load_parser_config
from services.parser.common.schema import TextBlock, TableBlock


pytestmark = pytest.mark.unit


def test_default_parser_uses_local_mineru():
    from services.parser.service import ParserService
    from services.parser.providers.mineru.pdf_parser import MineruDocumentParser
    from shared.config import ParserConfig

    assert isinstance(ParserService(ParserConfig()).pdf_parser, MineruDocumentParser)


@pytest.fixture(autouse=True)
def isolate_mineru_environment(monkeypatch):
    monkeypatch.delenv("MINERU_MODEL_BASE_DIR", raising=False)
    monkeypatch.delenv("MINERU_MODEL_SOURCE", raising=False)


def local_config(tmp_path, options=""):
    path = tmp_path / "parser.yaml"
    path.write_text("parser:\n  mineru:\n    enable: true\n" + options)
    return load_parser_config(path)


def test_local_mineru_config(tmp_path):
    config = local_config(tmp_path, "    tier: advanced\n    parse_method: ocr\n")
    assert config.active == "mineru"
    assert config.mineru.tier == "advanced"
    assert config.mineru.parse_method == "ocr"


@pytest.mark.parametrize("option", ["tier: vlm", "parse_method: invalid"])
def test_local_mineru_rejects_invalid_options(tmp_path, option):
    with pytest.raises(ValueError, match="mineru\\."):
        local_config(tmp_path, "    " + option + "\n")


def install_sdk(monkeypatch, content):
    package = ModuleType("mineru")
    parser = ModuleType("mineru.parser")
    api_server = ModuleType("mineru.parser.api_server")
    api_server._preload_server_models = Mock()
    parser.preload = api_server._preload_server_models
    render = ModuleType("mineru.render")
    parser.parse = Mock(return_value=SimpleNamespace(middle_json=object()))
    render.render = Mock(return_value=content)
    render.RenderFormat = SimpleNamespace(CONTENT_LIST="content_list")
    monkeypatch.setitem(sys.modules, "mineru", package)
    monkeypatch.setitem(sys.modules, "mineru.parser", parser)
    monkeypatch.setitem(sys.modules, "mineru.parser.api_server", api_server)
    monkeypatch.setitem(sys.modules, "mineru.render", render)
    return parser, render


@pytest.mark.parametrize("tier", ["basic", "standard", "advanced"])
def test_local_mineru_preloads_before_ready(tmp_path, monkeypatch, tier):
    from services.parser.service import ParserService

    sdk, _ = install_sdk(monkeypatch, [])
    service = ParserService(local_config(tmp_path, f"    tier: {tier}\n"))
    def preload(_):
        assert not service.pdf_parser.ready
    sdk.preload.side_effect = preload
    service.start()
    sdk.preload.assert_called_once_with(tier)
    assert service.ready
    sdk.parse.assert_not_called()


def test_local_mineru_preload_failure_is_not_ready(tmp_path, monkeypatch):
    from services.parser.service import ParserService

    sdk, _ = install_sdk(monkeypatch, [])
    sdk.preload.side_effect = RuntimeError("model assets missing")
    service = ParserService(local_config(tmp_path))
    with pytest.raises(RuntimeError, match="model assets missing"):
        service.start()
    assert not service.ready
    assert not service.pdf_parser.ready


def test_local_mineru_parses_full_document_and_preserves_blocks(tmp_path, monkeypatch):
    from services.parser.service import ParserService

    parser, render = install_sdk(monkeypatch, [
        {"type": "text", "text": "Heading", "text_level": 1, "page_idx": 0},
        {"type": "table", "table_caption": ["Table"], "rows": [["A", "B"], ["1", "2"]], "page_idx": 6},
    ])
    service = ParserService(local_config(tmp_path))
    service.start()
    blocks = service.pdf_parser.parse_file("document.pdf")
    parser.parse.assert_called_once_with("document.pdf", tier="basic", ocr_mode="auto", image_analysis=False)
    render.render.assert_called_once_with(parser.parse.return_value.middle_json, "content_list")
    assert blocks == [TextBlock("Heading", page=1, kind="heading"), TableBlock(rows=[["A", "B"], ["1", "2"]], caption="Table", page=7)]
    service.stop()
    assert not service.ready


def test_local_mineru_propagates_sdk_errors(tmp_path, monkeypatch):
    from services.parser.service import ParserService

    parser, _ = install_sdk(monkeypatch, [])
    parser.parse.side_effect = RuntimeError("model assets missing")
    service = ParserService(local_config(tmp_path))
    with pytest.raises(RuntimeError, match="model assets missing"):
        service.pdf_parser.parse_file("document.pdf")


def test_local_mineru_rejects_empty_output(tmp_path, monkeypatch):
    from services.parser.service import ParserService
    from services.parser.common.validation import InvalidDocumentError

    install_sdk(monkeypatch, [])
    service = ParserService(local_config(tmp_path))
    with pytest.raises(InvalidDocumentError, match="Empty file: report.pdf"):
        service.pdf_parser.parse_file("download.pdf", original_filename="report.pdf")
