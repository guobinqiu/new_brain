import os

import pytest


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_MINERU_INTEGRATION") != "1",
        reason="set RUN_MINERU_INTEGRATION=1 to run inference with local MinerU models",
    ),
]


def test_mineru_pipeline_parses_real_pdf(tmp_path):
    import pymupdf

    from services.parser.common.schema import FormulaBlock, TableBlock, TextBlock
    from services.parser.providers.mineru.pdf_pipeline import MineruPipelineDocumentParser
    from shared.config import MineruParserConfig

    pdf_path = tmp_path / "mineru-pipeline.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "MinerU pipeline integration")
        document.save(str(pdf_path))

    parser = MineruPipelineDocumentParser(
        MineruParserConfig(parse_method="txt", formula=False, table_enable=False),
    )
    try:
        parser.start()
        assert parser.ready, "MinerU pipeline did not start; install local models before running this test"
        blocks = parser.parse_file(str(pdf_path), original_filename=pdf_path.name)
    finally:
        parser.stop()

    assert blocks
    assert all(isinstance(block, (TextBlock, TableBlock, FormulaBlock)) for block in blocks)
    text_blocks = [block for block in blocks if isinstance(block, TextBlock)]
    assert "MinerU pipeline integration" in " ".join(block.text for block in text_blocks)
    assert all(block.page == 1 for block in blocks)
