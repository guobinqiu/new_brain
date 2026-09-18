import pytest


pytestmark = pytest.mark.unit


def test_mineru_vlm_parser_uses_vlm_auto_engine_for_pdf(monkeypatch):
    import services.parser.providers.mineru as mineru
    from services.parser.common.schema import TextBlock
    from services.parser.providers.mineru.pdf_vlm import MineruVlmDocumentParser
    from shared.config import MineruVlmParserConfig

    calls = []

    def fake_parse_document_blocks(filepath, filename, file_type, parser_config=None, backend="pipeline"):
        assert parser_config is None
        calls.append((filepath, filename, file_type, backend))
        return [TextBlock("vlm content")]

    monkeypatch.setattr(mineru, "parse_document_blocks", fake_parse_document_blocks)

    blocks = MineruVlmDocumentParser(MineruVlmParserConfig()).parse_file("/tmp/demo.pdf", original_filename="demo.pdf")

    assert blocks == [TextBlock("vlm content")]
    assert calls == [("/tmp/demo.pdf", "demo.pdf", "pdf", "vlm-auto-engine")]
