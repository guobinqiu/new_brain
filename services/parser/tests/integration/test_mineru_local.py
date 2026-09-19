import importlib.util

import pytest


pytestmark = pytest.mark.integration


def test_mineru4_flash_parses_all_pages(tmp_path, monkeypatch):
    if importlib.util.find_spec("mineru") is None:
        pytest.skip("MinerU 4.0 is not installed")
    import pymupdf

    from services.parser.providers.mineru.pdf_parser import MineruDocumentParser
    from shared.config import MineruParserConfig

    monkeypatch.setenv("MINERU_MODEL_SOURCE", "local")
    path = tmp_path / "twelve-pages.pdf"
    with pymupdf.open() as document:
        for number in range(1, 13):
            document.new_page().insert_text((72, 72), f"Page {number} contains a unique verification sentence.")
        document.save(path)

    parser = MineruDocumentParser(MineruParserConfig(tier="flash", parse_method="txt"))
    try:
        blocks = parser.parse_file(str(path))
        assert {block.page for block in blocks} == set(range(1, 13))
        assert any("Page 12 contains" in block.text for block in blocks)
    finally:
        parser.stop()
