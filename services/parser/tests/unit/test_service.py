import threading
import time

from services.parser.service import ParserService
from shared.config import ParserConfig


class SlowDocumentParser:
    ready = True

    def __init__(self):
        self.active = 0
        self.max_active = 0

    def parse_file(self, filepath: str, *, original_filename: str | None = None) -> list[dict]:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        self.active -= 1
        return [{"id": filepath, "content": original_filename or filepath, "metadata": {}}]


def test_parser_service_serializes_parse_file_calls(monkeypatch):
    import services.parser.service as service_mod

    monkeypatch.setattr(service_mod, "validate_pdf_file", lambda filepath: None)
    service = ParserService(ParserConfig())
    parser = SlowDocumentParser()
    service.pdf_parser = parser

    threads = [
        threading.Thread(target=service.parse_file, args=(f"file-{index}.pdf",), kwargs={"original_filename": f"file-{index}.pdf"})
        for index in range(2)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert parser.max_active == 1


def test_parser_service_uses_distinct_docling_pipeline_and_vlm_backends(monkeypatch):
    import services.parser.service as service_mod
    from shared.config import DoclingParserConfig, DoclingVlmParserConfig

    class FakeDoclingPipelineDocumentParser:
        def __init__(self, config):
            self.config = config

    class FakeDoclingVlmDocumentParser:
        def __init__(self, config):
            self.config = config

    monkeypatch.setattr(service_mod, "DoclingPipelineDocumentParser", FakeDoclingPipelineDocumentParser)
    monkeypatch.setattr(service_mod, "DoclingVlmDocumentParser", FakeDoclingVlmDocumentParser)

    pipeline_service = ParserService(ParserConfig(active="docling", docling=DoclingParserConfig(formula=True, table_enable=True)))
    vlm_service = ParserService(ParserConfig(active="docling_vlm", docling_vlm=DoclingVlmParserConfig(model="granitedocling")))

    assert isinstance(pipeline_service.pdf_parser, FakeDoclingPipelineDocumentParser)
    assert pipeline_service.pdf_parser.config.formula is True
    assert pipeline_service.pdf_parser.config.table_enable is True
    assert isinstance(vlm_service.pdf_parser, FakeDoclingVlmDocumentParser)
    assert vlm_service.pdf_parser.config.model == "granitedocling"


def test_parser_service_uses_mineru_api_server_backend(monkeypatch):
    import services.parser.service as service_mod
    from shared.config import MineruParserConfig

    class FakeMineruApiServerDocumentParser:
        def __init__(self, config):
            self.config = config

    monkeypatch.setattr(service_mod, "MineruApiServerDocumentParser", FakeMineruApiServerDocumentParser)

    service = ParserService(ParserConfig(active="mineru", mineru=MineruParserConfig()))

    assert isinstance(service.pdf_parser, FakeMineruApiServerDocumentParser)


def test_parser_service_routes_txt_to_local_parser_when_docling_is_active(tmp_path, monkeypatch):
    import services.parser.service as service_mod

    class FailingDoclingParser:
        ready = True

        def __init__(self, config):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def parse_file(self, filepath, *, original_filename=None):
            raise AssertionError("txt should not be parsed by docling")

    monkeypatch.setattr(service_mod, "DoclingPipelineDocumentParser", FailingDoclingParser)
    text_file = tmp_path / "a.txt"
    text_file.write_text("本地文本解析", encoding="utf-8")

    blocks = ParserService(ParserConfig(active="docling")).parse_file(str(text_file))

    assert blocks[0].text == "本地文本解析"


def test_parser_service_routes_pptx_to_local_parser_when_docling_is_active(tmp_path, monkeypatch):
    import services.parser.service as service_mod
    from services.parser.common.schema import TableBlock
    from pptx import Presentation

    class FailingDoclingParser:
        ready = True

        def __init__(self, config):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def parse_file(self, filepath, *, original_filename=None):
            raise AssertionError("pptx should not be parsed by docling")

    monkeypatch.setattr(service_mod, "DoclingPipelineDocumentParser", FailingDoclingParser)
    pptx_file = tmp_path / "slides.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "能力概览"
    table = slide.shapes.add_table(2, 2, 0, 0, 1000, 1000).table
    table.cell(0, 0).text = "类型"
    table.cell(0, 1).text = "说明"
    table.cell(1, 0).text = "PPT"
    table.cell(1, 1).text = "原生解析"
    presentation.save(str(pptx_file))

    blocks = ParserService(ParserConfig(active="docling")).parse_file(str(pptx_file))

    assert blocks[0].text == "能力概览"
    assert any(isinstance(block, TableBlock) and ["PPT", "原生解析"] in block.rows for block in blocks)


def test_parser_service_routes_legacy_office_through_conversion(tmp_path, monkeypatch):
    import services.parser.service as service_mod
    from services.parser.common.schema import TextBlock

    converted_paths = []

    class FakeConversion:
        def __init__(self, filepath, target_suffix):
            self.filepath = filepath
            self.target_suffix = target_suffix
            self.converted = tmp_path / f"converted{target_suffix}"

        def __enter__(self):
            self.converted.write_text("converted", encoding="utf-8")
            converted_paths.append((self.filepath, self.target_suffix, str(self.converted)))
            return self.converted

        def __exit__(self, exc_type, exc, traceback):
            pass

    def fake_convert(filepath, target_suffix):
        return FakeConversion(filepath, target_suffix)

    def fake_parse(self, filepath):
        return [TextBlock(f"parsed:{filepath}")]

    monkeypatch.setattr("services.parser.documents.parser.convert_legacy_office_file", fake_convert)
    monkeypatch.setattr("services.parser.documents.docx.DocxBlockParser.parse", fake_parse)
    monkeypatch.setattr("services.parser.documents.xlsx.XlsxBlockParser.parse", fake_parse)
    monkeypatch.setattr("services.parser.documents.pptx.PptxBlockParser.parse", fake_parse)

    service = ParserService(ParserConfig(active="docling"))

    for suffix, target_suffix in ((".doc", ".docx"), (".xls", ".xlsx"), (".ppt", ".pptx")):
        source = tmp_path / f"legacy{suffix}"
        source.write_bytes(b"legacy")

        blocks = service.parse_file(str(source))

        assert converted_paths[-1][0] == str(source)
        assert converted_paths[-1][1] == target_suffix
        assert blocks[0].text == f"parsed:{converted_paths[-1][2]}"
