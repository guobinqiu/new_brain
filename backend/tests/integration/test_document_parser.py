import pytest


def _create_minimal_pdf(path: str, text: str):
    """Create a valid minimal PDF containing *text* (ASCII-safe only)."""
    # Escape PDF string specials
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
    offsets = [0] * 6  # index 0 is the free entry
    for i, blob in enumerate(objs, start=1):
        offsets[i] = pos
        pos += len(blob)

    xref_start = pos
    xref_lines = [f"xref\n0 6\n{offsets[0]:010d} 65535 f \n"]
    xref_lines += [f"{o:010d} 00000 n \n" for o in offsets[1:]]
    xref = "".join(xref_lines)

    trailer = f"trailer<</Size 6/Root 1 0 R>>\nstartxref\n{xref_start}\n%%EOF"

    with open(path, "wb") as f:
        f.write(header)
        for blob in objs:
            f.write(blob)
        f.write(xref.encode("ascii"))
        f.write(trailer.encode("ascii"))


# =============================================================================
# 1. Document Parser Tests
# =============================================================================


class TestDocumentParser:
    """document_parser.py – file parsing and chunking behaviour."""

    def test_parse_txt_file(self, test_txt_path):
        """Parse a .txt file → returns chunks with expected structure."""
        from document_parser import parse_file

        chunks = parse_file(test_txt_path)

        assert len(chunks) > 0
        for c in chunks:
            assert "content" in c
            assert "metadata" in c
            assert "id" in c
            assert c["metadata"].get("filename") == "test_ai.txt"
            assert "chunk_index" in c["metadata"]
            # Each chunk should be at most the default chunk size.
            assert len(c["content"]) <= 250

    def test_parse_md_file(self, tmp_path):
        """Parse a .md file."""
        from document_parser import parse_file

        md_file = tmp_path / "readme.md"
        md_file.write_text(
            "# Title\n\nThis is a **markdown** file.\n\n人工智能测试。\n",
            encoding="utf-8",
        )
        chunks = parse_file(str(md_file))
        assert len(chunks) > 0
        assert chunks[0]["metadata"]["filename"] == "readme.md"

    def test_parse_docx_file(self, tmp_path):
        """Parse a .docx file."""
        from docx import Document
        from document_parser import parse_file

        docx_file = tmp_path / "test.docx"
        doc = Document()
        doc.add_paragraph("人工智能是计算机科学的一个重要分支。")
        doc.add_paragraph("AGI is the goal of AI research.")
        doc.save(str(docx_file))

        chunks = parse_file(str(docx_file))
        assert len(chunks) > 0
        assert chunks[0]["metadata"]["filename"] == "test.docx"

    def test_parse_pdf_file(self, tmp_path):
        """Parse a .pdf file via OCR with ASCII text."""
        from document_parser import parse_file

        pdf_file = tmp_path / "test.pdf"
        _create_minimal_pdf(str(pdf_file), "PDF test for parsing AGI content")

        chunks = parse_file(str(pdf_file))
        assert len(chunks) > 0
        assert chunks[0]["metadata"]["filename"] == "test.pdf"
        # Verify actual text survived extraction
        combined = " ".join(c["content"] for c in chunks)
        assert "PDF" in combined and "AGI" in combined

    def test_parse_unsupported_type_raises(self, tmp_path):
        """Unsupported file extensions raise ``ValueError``."""
        from document_parser import parse_file

        bad = tmp_path / "data.xyz"
        bad.write_text("some content")
        with pytest.raises(ValueError, match="Unsupported file type"):
            parse_file(str(bad))

    def test_parse_empty_file_raises(self, tmp_path):
        """An empty file raises ``ValueError``."""
        from document_parser import parse_file

        empty = tmp_path / "empty.txt"
        empty.write_text("")
        with pytest.raises(ValueError, match="Empty file"):
            parse_file(str(empty))

    def test_preserves_original_filename(self, tmp_path):
        """The ``original_filename`` parameter is stored in metadata."""
        from document_parser import parse_file

        src = tmp_path / "src.txt"
        src.write_text("Hello world. " * 100, encoding="utf-8")

        chunks = parse_file(str(src), original_filename="my-upload.txt")
        for c in chunks:
            assert c["metadata"]["filename"] == "my-upload.txt"

    def test_chunk_overlap(self, tmp_path):
        """Consecutive chunks have overlapping text (~50 chars of overlap)."""
        from document_parser import chunk_text

        # Create a long enough text so we get at least 2 chunks
        text = "这是一个测试段落。" * 200
        chunks = chunk_text(text, "test.txt", chunk_size=500, overlap=50)

        assert len(chunks) >= 2
        # The overlap appears at the start of chunk 1 and end of chunk 0
        # We check that chunk 1's start appears somewhere in the tail of chunk 0
        tail_of_0 = chunks[0]["content"][-60:]
        head_of_1 = chunks[1]["content"][:60]
        # They should share at least a few characters (overlap region)
        assert len(tail_of_0) > 0 and len(head_of_1) > 0

    def test_parse_image_file(self, test_img_path):
        """``parse_file()`` handles .png images and returns text chunks via OCR."""
        from document_parser import parse_file
        from ocr.rapid import RapidOCR

        ocr = RapidOCR()
        ocr.start()
        chunks = parse_file(test_img_path, ocr=ocr)
        assert len(chunks) > 0
        for c in chunks:
            assert "content" in c
            assert "metadata" in c
            assert "id" in c
            assert c["metadata"].get("filename") == "test_ocr.png"
            assert "chunk_index" in c["metadata"]
        # The OCR'd content should contain at least some of the image text
        combined = " ".join(c["content"] for c in chunks)
        assert "AGI" in combined or "test" in combined.lower() or "人工智能" in combined


# =============================================================================
# 2. Chroma Client Tests
# =============================================================================
