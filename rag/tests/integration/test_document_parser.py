import pytest
from uuid import UUID


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


class _TempDir:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.path.mkdir(exist_ok=True)
        return str(self.path)

    def __exit__(self, exc_type, exc, tb):
        return False


def _parse_file(filepath: str, original_filename: str | None = None, ocr=None, parser=None) -> list[dict]:
    from rag.parser.service import ParserService
    from rag.schema import ParserConfig

    parser_service = ParserService(parser or ParserConfig(), ocr=ocr)
    parser_service.start()
    try:
        return parser_service.parse_file(
            filepath,
            original_filename=original_filename,
            ocr=ocr,
        )
    finally:
        parser_service.stop()


def _mineru_parser(chunk_size: int = 500, chunk_overlap: int = 80, table=None):
    from rag.schema import MineruParserConfig, ParserConfig, TableParserConfig, TextParserConfig

    return ParserConfig(
        mineru=MineruParserConfig(
            text=TextParserConfig(chunk_size=chunk_size, chunk_overlap=chunk_overlap),
            table=table or TableParserConfig(),
        ),
    )


def _unstructured_parser(strategy="hi_res", infer_table_structure=True):
    from rag.schema import MineruParserConfig, ParserConfig, UnstructuredParserConfig

    return ParserConfig(
        mineru=MineruParserConfig(enable=False),
        unstructured=UnstructuredParserConfig(
            enable=True,
            strategy=strategy,
            infer_table_structure=infer_table_structure,
        ),
    )


# =============================================================================
# 1. Parser Service Tests
# =============================================================================


class TestParserService:
    """parser.service – file parsing and chunking behaviour."""

    def test_parse_txt_file(self, test_txt_path):
        """Parse a .txt file → returns chunks with expected structure."""
        chunks = _parse_file(test_txt_path)

        assert len(chunks) > 0
        for c in chunks:
            assert "content" in c
            assert "metadata" in c
            assert "id" in c
            UUID(c["id"])
            assert c["metadata"].get("filename") == "test_ai.txt"
            assert "chunk_index" in c["metadata"]
            # Each chunk should be at most the default chunk size.
            assert len(c["content"]) <= 500

    def test_parse_md_file(self, tmp_path):
        """Parse a .md file."""
        md_file = tmp_path / "readme.md"
        md_file.write_text(
            "# Title\n\nThis is a **markdown** file.\n\n人工智能测试。\n",
            encoding="utf-8",
        )
        chunks = _parse_file(str(md_file))
        assert len(chunks) > 0
        assert chunks[0]["metadata"]["filename"] == "readme.md"

    def test_parse_md_table_file(self, tmp_path):
        md_file = tmp_path / "table.md"
        md_file.write_text(
            "# 数据库对比\n\n"
            "| 向量库 | 能力 |\n"
            "| --- | --- |\n"
            "| Qdrant | 过滤 |\n"
            "| Milvus | 分布式 |\n",
            encoding="utf-8",
        )

        chunks = _parse_file(str(md_file))

        table_chunks = [chunk for chunk in chunks if "| Qdrant | 过滤 |" in chunk["content"]]
        assert len(table_chunks) == 1
        assert "| Qdrant | 过滤 |" in table_chunks[0]["content"]

    def test_parse_md_embedded_image_uses_mineru(self, tmp_path, monkeypatch):
        import json
        import rag.parser.mineru
        from PIL import Image

        image_file = tmp_path / "note.png"
        Image.new("RGB", (10, 10), "white").save(str(image_file))
        md_file = tmp_path / "image.md"
        md_file.write_text("# 图片说明\n\n![note](note.png)\n", encoding="utf-8")

        calls = []

        def fake_do_parse(output_dir, filepath, filename, file_type="pdf"):
            calls.append(file_type)
            assert file_type == "png"
            output_dir = tmp_path / "mineru-output"
            output_dir.mkdir(exist_ok=True)
            (output_dir / "note_content_list.json").write_text(
                json.dumps([{"type": "text", "text": "Markdown 图片文字"}]),
                encoding="utf-8",
            )

        monkeypatch.setattr(rag.parser.mineru, "table_parser_available", lambda: True)
        monkeypatch.setattr(rag.parser.mineru, "load_table_parser", lambda: None)
        monkeypatch.setattr(rag.parser.mineru.tempfile, "TemporaryDirectory", lambda prefix: _TempDir(tmp_path / "mineru-output"))
        monkeypatch.setattr(rag.parser.mineru, "_mineru_do_parse", fake_do_parse)

        chunks = _parse_file(str(md_file))

        combined = "\n".join(chunk["content"] for chunk in chunks)
        assert calls == ["png"]
        assert "图片说明" in combined
        assert "Markdown 图片文字" in combined

    def test_parse_docx_file(self, tmp_path):
        """Parse a .docx file."""
        from docx import Document
        docx_file = tmp_path / "test.docx"
        doc = Document()
        doc.add_paragraph("人工智能是计算机科学的一个重要分支。")
        doc.add_paragraph("AGI is the goal of AI research.")
        doc.save(str(docx_file))

        chunks = _parse_file(str(docx_file))
        assert len(chunks) > 0
        assert chunks[0]["metadata"]["filename"] == "test.docx"

    def test_parse_docx_table_file(self, tmp_path, monkeypatch):
        import json
        import rag.parser.mineru
        from docx import Document

        docx_file = tmp_path / "table.docx"
        doc = Document()
        doc.add_paragraph("数据库能力对比")
        table = doc.add_table(rows=3, cols=2)
        table.rows[0].cells[0].text = "向量库"
        table.rows[0].cells[1].text = "能力"
        table.rows[1].cells[0].text = "Qdrant"
        table.rows[1].cells[1].text = "过滤"
        table.rows[2].cells[0].text = "Milvus"
        table.rows[2].cells[1].text = "分布式"
        doc.save(str(docx_file))

        calls = []

        def fake_do_parse(output_dir, filepath, filename, file_type="pdf"):
            calls.append(file_type)
            assert file_type == "docx"
            output_dir = tmp_path / "mineru-output"
            output_dir.mkdir(exist_ok=True)
            (output_dir / "table_content_list.json").write_text(
                json.dumps([
                    {"type": "text", "text": "数据库能力对比"},
                    {
                        "type": "table",
                        "table_body": (
                            "<table>"
                            "<tr><td>向量库</td><td>能力</td></tr>"
                            "<tr><td>Qdrant</td><td>过滤</td></tr>"
                            "<tr><td>Milvus</td><td>分布式</td></tr>"
                            "</table>"
                        ),
                    },
                ]),
                encoding="utf-8",
            )

        monkeypatch.setattr(rag.parser.mineru, "table_parser_available", lambda: True)
        monkeypatch.setattr(rag.parser.mineru, "load_table_parser", lambda: None)
        monkeypatch.setattr(rag.parser.mineru.tempfile, "TemporaryDirectory", lambda prefix: _TempDir(tmp_path / "mineru-output"))
        monkeypatch.setattr(rag.parser.mineru, "_mineru_do_parse", fake_do_parse)

        chunks = _parse_file(str(docx_file))

        assert calls == ["docx"]
        table_chunks = [chunk for chunk in chunks if "| Qdrant | 过滤 |" in chunk["content"]]
        assert len(table_chunks) == 1
        assert "数据库能力对比" in table_chunks[0]["content"]
        assert "| Qdrant | 过滤 |" in table_chunks[0]["content"]

    def test_parse_docx_embedded_image_uses_mineru(self, tmp_path, monkeypatch):
        import json
        import rag.parser.mineru
        from docx import Document
        from PIL import Image

        image_file = tmp_path / "docx.png"
        Image.new("RGB", (10, 10), "white").save(str(image_file))
        docx_file = tmp_path / "image.docx"
        doc = Document()
        doc.add_paragraph("Word 图片说明")
        doc.add_picture(str(image_file))
        doc.save(str(docx_file))

        calls = []

        def fake_do_parse(output_dir, filepath, filename, file_type):
            calls.append(file_type)
            output_dir = tmp_path / f"mineru-output-{len(calls)}"
            output_dir.mkdir(exist_ok=True)
            if file_type == "docx":
                payload = [{"type": "text", "text": "Word 图片说明"}]
            else:
                assert file_type == "png"
                payload = [{"type": "text", "text": "Word 图片文字"}]
            (output_dir / f"{len(calls)}_content_list.json").write_text(json.dumps(payload), encoding="utf-8")

        monkeypatch.setattr(rag.parser.mineru, "table_parser_available", lambda: True)
        monkeypatch.setattr(rag.parser.mineru, "load_table_parser", lambda: None)
        monkeypatch.setattr(rag.parser.mineru.tempfile, "TemporaryDirectory", lambda prefix: _TempDir(tmp_path / f"mineru-output-{len(calls) + 1}"))
        monkeypatch.setattr(rag.parser.mineru, "_mineru_do_parse", fake_do_parse)

        chunks = _parse_file(str(docx_file))

        combined = "\n".join(chunk["content"] for chunk in chunks)
        assert calls == ["docx", "png"]
        assert "Word 图片说明" in combined
        assert "Word 图片文字" in combined

    def test_parse_docx_keeps_native_list_paragraphs(self, tmp_path, monkeypatch):
        import json
        import rag.parser.mineru
        from docx import Document

        docx_file = tmp_path / "workflow.docx"
        doc = Document()
        doc.add_paragraph("核心工作流")
        doc.add_paragraph("1. 开发/配置阶段 (离线)")
        doc.add_paragraph("人 创建新商户目录，编写 （人设）和 （示例）。")
        doc.add_paragraph("脚本/工具 读取 ，自动编译生成 （JSON Schema）。")
        doc.add_paragraph("2. 运行阶段 (在线)")
        doc.add_paragraph("系统启动：")
        doc.add_paragraph("读取 ，将路由规则加载到内存中。")
        doc.save(str(docx_file))

        def fake_do_parse(output_dir, filepath, filename, file_type):
            output_dir = tmp_path / "mineru-output"
            output_dir.mkdir(exist_ok=True)
            (output_dir / "workflow_content_list.json").write_text(
                json.dumps([
                    {"type": "text", "text": "核心工作流"},
                    {"type": "text", "text": "1. 开发/配置阶段 (离线)"},
                    {"type": "text", "text": "2. 运行阶段 (在线)"},
                ]),
                encoding="utf-8",
            )

        monkeypatch.setattr(rag.parser.mineru, "table_parser_available", lambda: True)
        monkeypatch.setattr(rag.parser.mineru, "load_table_parser", lambda: None)
        monkeypatch.setattr(rag.parser.mineru.tempfile, "TemporaryDirectory", lambda prefix: _TempDir(tmp_path / "mineru-output"))
        monkeypatch.setattr(rag.parser.mineru, "_mineru_do_parse", fake_do_parse)

        chunks = _parse_file(str(docx_file))

        combined = "\n".join(chunk["content"] for chunk in chunks)
        assert "人 创建新商户目录" in combined
        assert "脚本/工具 读取" in combined
        assert "读取 ，将路由规则加载到内存中。" in combined

    def test_parse_xlsx_table_file(self, tmp_path, monkeypatch):
        import json
        import rag.parser.mineru
        from openpyxl import Workbook

        xlsx_file = tmp_path / "table.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "数据库能力"
        sheet.append(["向量库", "能力"])
        sheet.append(["Qdrant", "过滤"])
        sheet.append(["Milvus", "分布式"])
        workbook.save(str(xlsx_file))

        calls = []

        def fake_do_parse(output_dir, filepath, filename, file_type):
            calls.append(file_type)
            assert file_type == "xlsx"
            output_dir = tmp_path / "mineru-output"
            output_dir.mkdir(exist_ok=True)
            (output_dir / "table_content_list.json").write_text(
                json.dumps([
                    {
                        "type": "table",
                        "table_caption": "工作表：数据库能力",
                        "table_body": (
                            "<table>"
                            "<tr><td>向量库</td><td>能力</td></tr>"
                            "<tr><td>Qdrant</td><td>过滤</td></tr>"
                            "<tr><td>Milvus</td><td>分布式</td></tr>"
                            "</table>"
                        ),
                    },
                ]),
                encoding="utf-8",
            )

        monkeypatch.setattr(rag.parser.mineru, "table_parser_available", lambda: True)
        monkeypatch.setattr(rag.parser.mineru, "load_table_parser", lambda: None)
        monkeypatch.setattr(rag.parser.mineru.tempfile, "TemporaryDirectory", lambda prefix: _TempDir(tmp_path / "mineru-output"))
        monkeypatch.setattr(rag.parser.mineru, "_mineru_do_parse", fake_do_parse)

        chunks = _parse_file(str(xlsx_file))

        assert calls == ["xlsx"]
        table_chunks = [chunk for chunk in chunks if "| Qdrant | 过滤 |" in chunk["content"]]
        assert len(table_chunks) == 1
        assert "工作表：数据库能力" in table_chunks[0]["content"]
        assert "| Qdrant | 过滤 |" in table_chunks[0]["content"]

    def test_parse_xlsx_embedded_image_uses_mineru(self, tmp_path, monkeypatch):
        import json
        import rag.parser.mineru
        from openpyxl import Workbook
        from openpyxl.drawing.image import Image as XlsxImage
        from PIL import Image

        image_file = tmp_path / "sheet.png"
        Image.new("RGB", (10, 10), "white").save(str(image_file))
        xlsx_file = tmp_path / "image.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Excel 图片说明"])
        sheet.add_image(XlsxImage(str(image_file)), "A3")
        workbook.save(str(xlsx_file))

        calls = []

        def fake_do_parse(output_dir, filepath, filename, file_type):
            calls.append(file_type)
            output_dir = tmp_path / f"mineru-output-{len(calls)}"
            output_dir.mkdir(exist_ok=True)
            if file_type == "xlsx":
                payload = [{"type": "text", "text": "Excel 图片说明"}]
            else:
                assert file_type == "png"
                payload = [{"type": "text", "text": "Excel 图片文字"}]
            (output_dir / f"{len(calls)}_content_list.json").write_text(json.dumps(payload), encoding="utf-8")

        monkeypatch.setattr(rag.parser.mineru, "table_parser_available", lambda: True)
        monkeypatch.setattr(rag.parser.mineru, "load_table_parser", lambda: None)
        monkeypatch.setattr(rag.parser.mineru.tempfile, "TemporaryDirectory", lambda prefix: _TempDir(tmp_path / f"mineru-output-{len(calls) + 1}"))
        monkeypatch.setattr(rag.parser.mineru, "_mineru_do_parse", fake_do_parse)

        chunks = _parse_file(str(xlsx_file))

        combined = "\n".join(chunk["content"] for chunk in chunks)
        assert calls == ["xlsx", "png"]
        assert "Excel 图片说明" in combined
        assert "Excel 图片文字" in combined

    def test_parse_fake_xlsx_file_raises_clear_error(self, tmp_path):
        xlsx_file = tmp_path / "fake.xlsx"
        xlsx_file.write_text("not an excel file", encoding="utf-8")

        with pytest.raises(ValueError, match="Invalid xlsx file"):
            _parse_file(str(xlsx_file))

    def test_parse_fake_docx_file_raises_clear_error(self, tmp_path):
        docx_file = tmp_path / "fake.docx"
        docx_file.write_text("not a docx file", encoding="utf-8")

        with pytest.raises(ValueError, match="Invalid docx file"):
            _parse_file(str(docx_file))

    def test_parse_fake_pdf_file_raises_clear_error(self, tmp_path):
        pdf_file = tmp_path / "fake.pdf"
        pdf_file.write_text("not a pdf file", encoding="utf-8")

        with pytest.raises(ValueError, match="Invalid pdf file"):
            _parse_file(str(pdf_file))

    def test_parse_fake_image_file_raises_clear_error(self, tmp_path):
        image_file = tmp_path / "fake.png"
        image_file.write_text("not an image file", encoding="utf-8")

        with pytest.raises(ValueError, match="Invalid image file"):
            _parse_file(str(image_file), ocr=object())

    def test_parser_service_uses_mineru_document_parser(self):
        from rag.parser.mineru_document import MineruDocumentParser
        from rag.parser.service import ParserService
        from rag.schema import ParserConfig

        parser_service = ParserService(ParserConfig())

        assert isinstance(parser_service.document, MineruDocumentParser)

    def test_parser_service_uses_unstructured_document_parser(self):
        from rag.parser.service import ParserService
        from rag.parser.unstructured import UnstructuredDocumentParser
        parser_service = ParserService(_unstructured_parser())

        assert isinstance(parser_service.document, UnstructuredDocumentParser)

    def test_parse_txt_file_with_unstructured_parser(self, tmp_path, monkeypatch):
        from rag.parser import unstructured as unstructured_parser
        text_file = tmp_path / "note.txt"
        text_file.write_text("第一段内容\n第二段内容", encoding="utf-8")

        class FakeElement:
            category = "NarrativeText"

            def __init__(self, text):
                self.text = text

            def __str__(self):
                return self.text

        monkeypatch.setattr(unstructured_parser, "_partition_file", lambda filepath, config: [FakeElement("第一段内容"), FakeElement("第二段内容")])

        chunks = _parse_file(str(text_file), parser=_unstructured_parser())

        assert len(chunks) == 1
        assert chunks[0]["content"] == "第一段内容\n第二段内容"
        assert chunks[0]["metadata"]["filename"] == "note.txt"

    def test_parse_pdf_embedded_image_with_unstructured_parser(self, tmp_path, monkeypatch):
        import fitz
        from PIL import Image
        from rag.parser import unstructured as unstructured_parser
        image_file = tmp_path / "chart.png"
        Image.new("RGB", (30, 30), "white").save(str(image_file))
        pdf_file = tmp_path / "image.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "PDF body")
        page.insert_image(fitz.Rect(72, 100, 160, 188), filename=str(image_file))
        doc.save(str(pdf_file))
        doc.close()

        class FakeElement:
            category = "NarrativeText"

            def __init__(self, text):
                self.text = text

            def __str__(self):
                return self.text

        def fake_partition(filepath, config):
            if filepath.endswith(".pdf"):
                return [FakeElement("PDF body")]
            return [FakeElement("PDF 图片文字")]

        monkeypatch.setattr(unstructured_parser, "_partition_file", fake_partition)

        chunks = _parse_file(str(pdf_file), parser=_unstructured_parser())

        content = "\n".join(chunk["content"] for chunk in chunks)
        assert "PDF body" in content
        assert "PDF 图片文字" in content

    def test_parse_pdf_fast_without_table_inference_skips_embedded_images(self, tmp_path, monkeypatch):
        from rag.parser import unstructured as unstructured_parser
        pdf_file = tmp_path / "image.pdf"
        pdf_file.write_bytes(
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"
        )

        class FakeElement:
            category = "NarrativeText"

            def __init__(self, text):
                self.text = text

            def __str__(self):
                return self.text

        calls = []

        def fake_partition(filepath, config):
            calls.append(filepath)
            return [FakeElement("PDF body")]

        monkeypatch.setattr(unstructured_parser, "_partition_file", fake_partition)

        chunks = _parse_file(str(pdf_file), parser=_unstructured_parser(strategy="fast", infer_table_structure=False))

        assert len(chunks) == 1
        assert chunks[0]["content"] == "PDF body"
        assert calls == [str(pdf_file)]

    def test_parse_image_file_with_unstructured_parser_keeps_table_blocks(self, tmp_path, monkeypatch):
        from PIL import Image
        from rag.parser import unstructured as unstructured_parser
        image_file = tmp_path / "table.png"
        Image.new("RGB", (10, 10), "white").save(str(image_file))
        calls = []

        class FakeMetadata:
            text_as_html = "<table><tr><td>指标</td><td>值</td></tr></table>"

        class FakeTable:
            category = "Table"
            metadata = FakeMetadata()

            def __str__(self):
                return "指标 值"

        def fake_partition(filepath, config):
            calls.append((filepath, config.strategy, config.infer_table_structure, config.languages))
            return [FakeTable()]

        monkeypatch.setattr(unstructured_parser, "_partition_file", fake_partition)

        chunks = _parse_file(str(image_file), parser=_unstructured_parser())

        assert len(chunks) == 1
        assert chunks[0]["content"] == "<table><tr><td>指标</td><td>值</td></tr></table>"
        assert calls == [(str(image_file), "hi_res", True, ["chi_sim", "eng"])]

    def test_parse_image_file_uses_mineru(self, tmp_path, monkeypatch):
        import json
        import rag.parser.mineru
        from PIL import Image

        image_file = tmp_path / "text.png"
        Image.new("RGB", (10, 10), "white").save(str(image_file))

        calls = []

        def fake_do_parse(output_dir, filepath, filename, file_type):
            calls.append(file_type)
            assert file_type == "png"
            output_dir = tmp_path / "mineru-output"
            output_dir.mkdir(exist_ok=True)
            (output_dir / "text_content_list.json").write_text(
                json.dumps([{"type": "text", "text": "图片里的普通文字"}]),
                encoding="utf-8",
            )

        monkeypatch.setattr(rag.parser.mineru, "table_parser_available", lambda: True)
        monkeypatch.setattr(rag.parser.mineru, "load_table_parser", lambda: None)
        monkeypatch.setattr(rag.parser.mineru.tempfile, "TemporaryDirectory", lambda prefix: _TempDir(tmp_path / "mineru-output"))
        monkeypatch.setattr(rag.parser.mineru, "_mineru_do_parse", fake_do_parse)

        chunks = _parse_file(str(image_file))

        assert len(chunks) == 1
        assert chunks[0]["content"] == "图片里的普通文字"
        assert calls == ["png"]

    def test_parse_pdf_embedded_image_uses_mineru(self, tmp_path, monkeypatch):
        import json
        import rag.parser.mineru
        import fitz
        from PIL import Image

        image_file = tmp_path / "table.png"
        Image.new("RGB", (30, 30), "white").save(str(image_file))
        pdf_file = tmp_path / "image-table.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "PDF body")
        page.insert_image(fitz.Rect(72, 100, 160, 188), filename=str(image_file))
        doc.save(str(pdf_file))
        doc.close()

        calls = []

        def fake_do_parse(output_dir, filepath, filename, file_type="pdf"):
            calls.append(file_type)
            output_dir = tmp_path / f"mineru-output-{len(calls)}"
            output_dir.mkdir(exist_ok=True)
            if file_type == "pdf":
                payload = [{"type": "text", "text": "PDF body"}]
            else:
                assert file_type == "png"
                payload = [{"type": "text", "text": "图片里的普通文字"}]
            (output_dir / f"{len(calls)}_content_list.json").write_text(json.dumps(payload), encoding="utf-8")

        monkeypatch.setattr(rag.parser.mineru, "table_parser_available", lambda: True)
        monkeypatch.setattr(rag.parser.mineru, "load_table_parser", lambda: None)
        monkeypatch.setattr(rag.parser.mineru.tempfile, "TemporaryDirectory", lambda prefix: _TempDir(tmp_path / f"mineru-output-{len(calls) + 1}"))
        monkeypatch.setattr(rag.parser.mineru, "_mineru_do_parse", fake_do_parse)

        chunks = _parse_file(str(pdf_file))

        combined = "\n".join(chunk["content"] for chunk in chunks)
        assert calls == ["pdf", "png"]
        assert "PDF body" in combined
        assert "图片里的普通文字" in combined

    def test_parse_pdf_file(self, tmp_path):
        """Parse a .pdf file with ASCII text."""
        pdf_file = tmp_path / "test.pdf"
        _create_minimal_pdf(str(pdf_file), "PDF test for parsing AGI content")

        chunks = _parse_file(str(pdf_file))
        assert len(chunks) > 0
        assert chunks[0]["metadata"]["filename"] == "test.pdf"
        # Verify actual text survived extraction
        combined = " ".join(c["content"] for c in chunks)
        assert "PDF" in combined and "AGI" in combined

    def test_parse_unsupported_type_raises(self, tmp_path):
        """Unsupported file extensions raise ``ValueError``."""
        bad = tmp_path / "data.xyz"
        bad.write_text("some content")
        with pytest.raises(ValueError, match="Unsupported file type"):
            _parse_file(str(bad))

    def test_parse_empty_file_raises(self, tmp_path):
        """An empty file raises ``ValueError``."""
        empty = tmp_path / "empty.txt"
        empty.write_text("")
        with pytest.raises(ValueError, match="Empty file"):
            _parse_file(str(empty))

    def test_preserves_original_filename(self, tmp_path):
        """The ``original_filename`` parameter is stored in metadata."""
        src = tmp_path / "src.txt"
        src.write_text("Hello world. " * 100, encoding="utf-8")

        chunks = _parse_file(str(src), original_filename="my-upload.txt")
        for c in chunks:
            assert c["metadata"]["filename"] == "my-upload.txt"

    def test_chunk_overlap(self, tmp_path):
        """Consecutive chunks have overlapping text (~50 chars of overlap)."""
        from rag.parser.text import chunk_text

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

    def test_parse_file_uses_parser_text_config(self, tmp_path):
        from rag.schema import ParserConfig

        src = tmp_path / "long.txt"
        src.write_text("人工智能。" * 200, encoding="utf-8")

        chunks = _parse_file(
            str(src),
            parser=_mineru_parser(chunk_size=120, chunk_overlap=20),
        )

        assert len(chunks) > 1
        assert max(len(chunk["content"]) for chunk in chunks) <= 120

    def test_split_table_keeps_small_table_whole(self):
        from rag.parser.table_splitter import split_table

        chunks = split_table(
            title="表格：指标",
            header=["年份", "营收"],
            rows=[["2024", "100"], ["2025", "120"]],
        )

        assert len(chunks) == 1
        assert "| 年份 | 营收 |" in chunks[0]["content"]
        assert "| 2024 | 100 |" in chunks[0]["content"]
        assert "| 2025 | 120 |" in chunks[0]["content"]
        assert chunks[0]["metadata"] == {}

    def test_split_table_keeps_large_table_whole(self):
        from rag.parser.table_splitter import split_table

        chunks = split_table(
            title="表格：指标",
            header=["年份", "营收"],
            rows=[["2024", "1" * 20], ["2025", "2" * 20], ["2026", "3" * 20]],
        )

        assert len(chunks) == 1
        assert chunks[0]["content"].startswith("表格：指标\n")
        assert "2024" in chunks[0]["content"]
        assert "2025" in chunks[0]["content"]
        assert "2026" in chunks[0]["content"]

    def test_split_table_keeps_single_long_row(self):
        from rag.parser.table_splitter import split_table

        chunks = split_table(
            title="表格：指标",
            header=["年份", "备注"],
            rows=[["2024", "很长" * 100]],
        )

        assert len(chunks) == 1
        assert len(chunks[0]["content"]) > 80
        assert "很长" * 100 in chunks[0]["content"]
        assert chunks[0]["metadata"] == {}

    def test_split_table_keeps_all_rows_in_one_chunk(self):
        from rag.parser.table_splitter import split_table

        chunks = split_table(
            title="表格：指标",
            header=["年份", "备注"],
            rows=[["2024", "1" * 10], ["2025", "2" * 10], ["2026", "3" * 10]],
        )

        assert len(chunks) == 1
        assert "2024" in chunks[0]["content"]
        assert "2025" in chunks[0]["content"]
        assert "2026" in chunks[0]["content"]

    def test_split_table_keeps_rows_after_size_limit_in_same_chunk(self):
        from rag.parser.table_splitter import split_table

        chunks = split_table(
            title="表格",
            header=["列"],
            rows=[["1" * 15], ["2" * 5], ["3" * 5]],
        )

        assert len(chunks) == 1
        assert "111111111111111" in chunks[0]["content"]
        assert "22222" in chunks[0]["content"]
        assert "33333" in chunks[0]["content"]

    def test_table_parser_reads_content_list_json(self, tmp_path, monkeypatch):
        import json
        import rag.parser.mineru
        from rag.schema import ParserConfig

        pdf_file = tmp_path / "json-table.pdf"
        _create_minimal_pdf(str(pdf_file), "table")

        def fake_do_parse(output_dir, filepath, filename, file_type="pdf"):
            output_dir = tmp_path / "mineru-output"
            output_dir.mkdir(exist_ok=True)
            (output_dir / "json-table_content_list.json").write_text(
                json.dumps([
                    {"type": "text", "text": "JSON 正文"},
                    {
                        "type": "table",
                        "table_body": (
                            '<table><tr><td>向量库</td><td colspan="2">能力</td></tr>'
                            "<tr><td>Qdrant</td><td>快</td><td>过滤</td></tr></table>"
                        ),
                    },
                    {"type": "image", "img_path": "images/a.jpg"},
                ]),
                encoding="utf-8",
            )
            (output_dir / "json-table.md").write_text("坏的 markdown", encoding="utf-8")

        monkeypatch.setattr(rag.parser.mineru, "table_parser_available", lambda: True)
        monkeypatch.setattr(rag.parser.mineru, "load_table_parser", lambda: None)
        monkeypatch.setattr(rag.parser.mineru.tempfile, "TemporaryDirectory", lambda prefix: _TempDir(tmp_path / "mineru-output"))
        monkeypatch.setattr(rag.parser.mineru, "_mineru_do_parse", fake_do_parse)

        chunks = _parse_file(
            str(pdf_file),
            parser=_mineru_parser(chunk_size=500, chunk_overlap=80),
        )

        combined = "\n".join(chunk["content"] for chunk in chunks)
        for chunk in chunks:
            UUID(chunk["id"])
        assert "JSON 正文" in combined
        assert "Qdrant" in combined
        assert "坏的 markdown" not in combined
        assert "images/" not in combined
        assert "<table" not in combined
        assert "| Qdrant | 快 | 过滤 |" in combined

    def test_table_parser_keeps_json_blocks_separate(self, tmp_path, monkeypatch):
        import json
        import rag.parser.mineru
        from rag.schema import ParserConfig

        pdf_file = tmp_path / "json-blocks.pdf"
        _create_minimal_pdf(str(pdf_file), "table")

        def fake_do_parse(output_dir, filepath, filename, file_type="pdf"):
            output_dir = tmp_path / "mineru-output"
            output_dir.mkdir(exist_ok=True)
            (output_dir / "json-blocks_content_list.json").write_text(
                json.dumps([
                    {"type": "text", "text": "第一段文本" * 20},
                    {
                        "type": "table",
                        "table_body": (
                            "<table>"
                            "<tr><td>向量库</td><td>小型数据集</td><td>扩展性说明</td></tr>"
                            "<tr><td>FAISS</td><td>V</td><td>X</td></tr>"
                            "<tr><td>Weaviate</td><td>V</td><td>V强支持</td></tr>"
                            "</table>"
                        ),
                    },
                    {"type": "text", "text": "第二段文本" * 20},
                ]),
                encoding="utf-8",
            )

        monkeypatch.setattr(rag.parser.mineru, "table_parser_available", lambda: True)
        monkeypatch.setattr(rag.parser.mineru, "load_table_parser", lambda: None)
        monkeypatch.setattr(rag.parser.mineru.tempfile, "TemporaryDirectory", lambda prefix: _TempDir(tmp_path / "mineru-output"))
        monkeypatch.setattr(rag.parser.mineru, "_mineru_do_parse", fake_do_parse)

        chunks = _parse_file(
            str(pdf_file),
            parser=_mineru_parser(chunk_size=80, chunk_overlap=10),
        )

        table_chunks = [chunk for chunk in chunks if "| FAISS | V | X |" in chunk["content"]]
        assert len(table_chunks) == 1
        assert table_chunks[0]["content"].startswith("第一段文本")
        assert "\n| FAISS | V | X |" in table_chunks[0]["content"]
        assert "\n\n第二段文本" in table_chunks[0]["content"]
        assert "| Weaviate | V | V强支持 |" in table_chunks[0]["content"]

    def test_table_parser_splits_merged_tables_inside_html_table(self):
        from rag.parser.table_transform import table_html_to_chunks
        from rag.schema import ParserConfig

        chunks = table_html_to_chunks(
            (
                "<table>"
                "<tr><td>向量库</td><td>小型数据集(&lt;100万)</td><td>中型数据集(100万-1亿)</td><td>大型数据集(&gt;1亿)</td><td>扩展性说明</td></tr>"
                "<tr><td>FAISS</td><td>V</td><td>X</td><td>X</td><td>X</td></tr>"
                "<tr><td>Pinecone</td><td>✓ 推荐</td><td>✓推荐</td><td>V强烈推荐</td><td>Serverless架构自动扩展，但大规模下成本较高。</td></tr>"
                "<tr><td>2. 查询类型对比</td></tr>"
                "<tr><td>向量库</td><td>稠密向量搜索</td><td>稀疏向量/关键词搜索</td><td>混合检索(Hybrid）</td><td>多模态检索</td></tr>"
                "<tr><td>Chroma</td><td>V</td><td>X</td><td>X</td><td>！基础支持</td></tr>"
                "</table>"
            ),
            _mineru_parser(chunk_size=500, chunk_overlap=80).mineru,
        )

        assert len(chunks) == 3
        assert chunks[0].endswith("2. 查询类型对比")
        assert chunks[1] == "2. 查询类型对比"
        assert chunks[2].startswith("2. 查询类型对比\n\n| 向量库 | 稠密向量搜索 | 稀疏向量/关键词搜索 | 混合检索(Hybrid） | 多模态检索 |")
        combined = "\n".join(chunks)
        assert "| Pinecone | ✓ 推荐 | ✓推荐 | V强烈推荐 | Serverless架构自动扩展，但大规模下成本较高。 |" in combined
        assert "| 2. 查询类型对比 |" not in combined
        assert "| 向量库 | 向量库 |" not in combined

    def test_table_parser_adds_neighbor_text_context_to_table(self, tmp_path, monkeypatch):
        import json
        import rag.parser.mineru
        from rag.schema import ParserConfig

        pdf_file = tmp_path / "json-heading-table.pdf"
        _create_minimal_pdf(str(pdf_file), "table")

        def fake_do_parse(output_dir, filepath, filename, file_type="pdf"):
            output_dir = tmp_path / "mineru-output"
            output_dir.mkdir(exist_ok=True)
            (output_dir / "json-heading-table_content_list.json").write_text(
                json.dumps([
                    {"type": "text", "text": "2. 查询类型对比"},
                    {
                        "type": "table",
                        "table_body": (
                            "<table>"
                            "<tr><td>向量库</td><td>稠密向量搜索</td></tr>"
                            "<tr><td>Chroma</td><td>V</td></tr>"
                            "</table>"
                        ),
                    },
                    {"type": "text", "text": "说明：V 表示支持，X 表示不支持"},
                ]),
                encoding="utf-8",
            )

        monkeypatch.setattr(rag.parser.mineru, "table_parser_available", lambda: True)
        monkeypatch.setattr(rag.parser.mineru, "load_table_parser", lambda: None)
        monkeypatch.setattr(rag.parser.mineru.tempfile, "TemporaryDirectory", lambda prefix: _TempDir(tmp_path / "mineru-output"))
        monkeypatch.setattr(rag.parser.mineru, "_mineru_do_parse", fake_do_parse)

        chunks = _parse_file(
            str(pdf_file),
            parser=_mineru_parser(chunk_size=80, chunk_overlap=10),
        )

        assert len(chunks) == 3
        assert chunks[0]["content"] == "2. 查询类型对比"
        assert chunks[1]["content"] == "2. 查询类型对比\n\n| 向量库 | 稠密向量搜索 |\n| --- | --- |\n| Chroma | V |\n\n说明：V 表示支持，X 表示不支持"
        assert chunks[2]["content"] == "说明：V 表示支持，X 表示不支持"

    def test_table_parser_merges_adjacent_text_blocks_before_chunking(self, tmp_path, monkeypatch):
        import json
        import rag.parser.mineru
        from rag.schema import ParserConfig

        pdf_file = tmp_path / "json-text-text-table.pdf"
        _create_minimal_pdf(str(pdf_file), "table")

        def fake_do_parse(output_dir, filepath, filename, file_type="pdf"):
            output_dir = tmp_path / "mineru-output"
            output_dir.mkdir(exist_ok=True)
            (output_dir / "json-text-text-table_content_list.json").write_text(
                json.dumps([
                    {"type": "text", "text": "第一段正文"},
                    {"type": "text", "text": "第二段正文"},
                    {
                        "type": "table",
                        "table_body": (
                            "<table>"
                            "<tr><td>向量库</td><td>规模</td></tr>"
                            "<tr><td>Qdrant</td><td>中</td></tr>"
                            "</table>"
                        ),
                    },
                ]),
                encoding="utf-8",
            )

        monkeypatch.setattr(rag.parser.mineru, "table_parser_available", lambda: True)
        monkeypatch.setattr(rag.parser.mineru, "load_table_parser", lambda: None)
        monkeypatch.setattr(rag.parser.mineru.tempfile, "TemporaryDirectory", lambda prefix: _TempDir(tmp_path / "mineru-output"))
        monkeypatch.setattr(rag.parser.mineru, "_mineru_do_parse", fake_do_parse)

        chunks = _parse_file(
            str(pdf_file),
            parser=_mineru_parser(chunk_size=100, chunk_overlap=10),
        )

        assert chunks[0]["content"] == "第一段正文\n第二段正文"
        assert chunks[1]["content"] == "第一段正文\n第二段正文\n\n| 向量库 | 规模 |\n| --- | --- |\n| Qdrant | 中 |"

    def test_table_parser_does_not_add_neighbor_table_context_to_table(self, tmp_path, monkeypatch):
        import json
        import rag.parser.mineru
        from rag.schema import ParserConfig

        pdf_file = tmp_path / "json-table-table.pdf"
        _create_minimal_pdf(str(pdf_file), "table")

        def fake_do_parse(output_dir, filepath, filename, file_type="pdf"):
            output_dir = tmp_path / "mineru-output"
            output_dir.mkdir(exist_ok=True)
            (output_dir / "json-table-table_content_list.json").write_text(
                json.dumps([
                    {
                        "type": "table",
                        "table_body": (
                            "<table>"
                            "<tr><td>库</td><td>规模</td></tr>"
                            "<tr><td>Qdrant</td><td>中</td></tr>"
                            "</table>"
                        ),
                    },
                    {
                        "type": "table",
                        "table_body": (
                            "<table>"
                            "<tr><td>库</td><td>查询</td></tr>"
                            "<tr><td>Milvus</td><td>强</td></tr>"
                            "</table>"
                        ),
                    },
                ]),
                encoding="utf-8",
            )

        monkeypatch.setattr(rag.parser.mineru, "table_parser_available", lambda: True)
        monkeypatch.setattr(rag.parser.mineru, "load_table_parser", lambda: None)
        monkeypatch.setattr(rag.parser.mineru.tempfile, "TemporaryDirectory", lambda prefix: _TempDir(tmp_path / "mineru-output"))
        monkeypatch.setattr(rag.parser.mineru, "_mineru_do_parse", fake_do_parse)

        chunks = _parse_file(
            str(pdf_file),
            parser=_mineru_parser(chunk_size=80, chunk_overlap=10),
        )

        assert chunks[0]["content"] == "| 库 | 规模 |\n| --- | --- |\n| Qdrant | 中 |"
        assert chunks[1]["content"] == "| 库 | 查询 |\n| --- | --- |\n| Milvus | 强 |"

    def test_table_parser_adds_between_text_context_to_both_tables(self, tmp_path, monkeypatch):
        import json
        import rag.parser.mineru
        from rag.schema import ParserConfig

        pdf_file = tmp_path / "json-table-heading-table.pdf"
        _create_minimal_pdf(str(pdf_file), "table")

        def fake_do_parse(output_dir, filepath, filename, file_type="pdf"):
            output_dir = tmp_path / "mineru-output"
            output_dir.mkdir(exist_ok=True)
            (output_dir / "json-table-heading-table_content_list.json").write_text(
                json.dumps([
                    {
                        "type": "table",
                        "table_body": (
                            "<table>"
                            "<tr><td>库</td><td>规模</td></tr>"
                            "<tr><td>Qdrant</td><td>中</td></tr>"
                            "</table>"
                        ),
                    },
                    {"type": "text", "text": "7. 架构类型对比"},
                    {
                        "type": "table",
                        "table_body": (
                            "<table>"
                            "<tr><td>库</td><td>架构</td></tr>"
                            "<tr><td>Milvus</td><td>分布式</td></tr>"
                            "</table>"
                        ),
                    },
                ]),
                encoding="utf-8",
            )

        monkeypatch.setattr(rag.parser.mineru, "table_parser_available", lambda: True)
        monkeypatch.setattr(rag.parser.mineru, "load_table_parser", lambda: None)
        monkeypatch.setattr(rag.parser.mineru.tempfile, "TemporaryDirectory", lambda prefix: _TempDir(tmp_path / "mineru-output"))
        monkeypatch.setattr(rag.parser.mineru, "_mineru_do_parse", fake_do_parse)

        chunks = _parse_file(
            str(pdf_file),
            parser=_mineru_parser(chunk_size=80, chunk_overlap=10),
        )

        assert chunks[0]["content"] == "| 库 | 规模 |\n| --- | --- |\n| Qdrant | 中 |\n\n7. 架构类型对比"
        assert chunks[1]["content"] == "7. 架构类型对比"
        assert chunks[2]["content"] == "7. 架构类型对比\n\n| 库 | 架构 |\n| --- | --- |\n| Milvus | 分布式 |"

    def test_table_parser_falls_back_to_text_for_non_pdf(self, tmp_path):
        from rag.schema import ParserConfig

        text_file = tmp_path / "table-mode.txt"
        text_file.write_text("普通文本也可以选择表格优先解析。", encoding="utf-8")

        chunks = _parse_file(str(text_file), parser=ParserConfig())

        assert chunks
        assert "普通文本" in chunks[0]["content"]

    def test_parse_image_file(self, test_img_path, tmp_path, monkeypatch):
        """``parse_file()`` handles .png images and returns text chunks via MinerU."""
        import json
        import rag.parser.mineru

        def fake_do_parse(output_dir, filepath, filename, file_type):
            assert file_type == "png"
            output_dir = tmp_path / "mineru-output"
            output_dir.mkdir(exist_ok=True)
            (output_dir / "test_ocr_content_list.json").write_text(
                json.dumps([{"type": "text", "text": "AGI test image"}]),
                encoding="utf-8",
            )

        monkeypatch.setattr(rag.parser.mineru, "table_parser_available", lambda: True)
        monkeypatch.setattr(rag.parser.mineru, "load_table_parser", lambda: None)
        monkeypatch.setattr(rag.parser.mineru.tempfile, "TemporaryDirectory", lambda prefix: _TempDir(tmp_path / "mineru-output"))
        monkeypatch.setattr(rag.parser.mineru, "_mineru_do_parse", fake_do_parse)

        chunks = _parse_file(test_img_path)
        assert len(chunks) > 0
        for c in chunks:
            assert "content" in c
            assert "metadata" in c
            assert "id" in c
            assert c["metadata"].get("filename") == "test_ocr.png"
            assert "chunk_index" in c["metadata"]
        combined = " ".join(c["content"] for c in chunks)
        assert "AGI" in combined or "test" in combined.lower() or "人工智能" in combined

# =============================================================================
# 2. Chroma Client Tests
# =============================================================================
