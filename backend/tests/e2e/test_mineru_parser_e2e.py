import os

import pytest


pytestmark = pytest.mark.e2e


def _create_minimal_pdf(path: str, text: str):
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content_stream = f"BT /F1 12 Tf 100 700 Td ({escaped}) Tj ET".encode("latin-1")
    content_len = len(content_stream)

    objs: list[bytes] = [
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n",
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n",
        b"3 0 obj<</Type/Page/Parent 2 0 R"
        b"/MediaBox[0 0 612 792]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n",
        (
            f"4 0 obj<</Length {content_len}>>stream\n".encode("latin-1")
            + content_stream
            + b"\nendstream\nendobj\n"
        ),
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n",
    ]

    header = b"%PDF-1.4\n"
    pos = len(header)
    offsets = [0] * 6
    for i, blob in enumerate(objs, start=1):
        offsets[i] = pos
        pos += len(blob)

    xref_start = pos
    xref_lines = [f"xref\n0 6\n{offsets[0]:010d} 65535 f \n"]
    xref_lines += [f"{o:010d} 00000 n \n" for o in offsets[1:]]
    trailer = f"trailer<</Size 6/Root 1 0 R>>\nstartxref\n{xref_start}\n%%EOF"

    with open(path, "wb") as f:
        f.write(header)
        for blob in objs:
            f.write(blob)
        f.write("".join(xref_lines).encode("ascii"))
        f.write(trailer.encode("ascii"))


def test_mineru_parser_runs_real_pipeline(tmp_path):
    if os.environ.get("RUN_MINERU_E2E") != "1":
        pytest.skip("set RUN_MINERU_E2E=1 to run MinerU inference")

    from parser.service import ParserService
    from parser.table import load_table_parser, table_parser_available
    from schema import ParserConfig

    if not table_parser_available():
        pytest.skip("MinerU model directory is not available")

    pdf_path = tmp_path / "mineru-e2e.pdf"
    _create_minimal_pdf(str(pdf_path), "MinerU E2E table parser")

    load_table_parser()
    parser_service = ParserService(ParserConfig())
    parser_service.start()
    try:
        chunks = parser_service.parse_file(
            str(pdf_path),
            original_filename="mineru-e2e.pdf",
        )
    finally:
        parser_service.stop()

    assert chunks
    assert all(chunk["metadata"]["filename"] == "mineru-e2e.pdf" for chunk in chunks)
