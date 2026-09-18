from services.parser.common.validation import InvalidDocumentError
import logging
import os
import time
from pathlib import Path

from services.parser.common.schema import Block
from services.parser.providers.docling.normalizer import normalize_docling_document
from shared.config import DoclingParserConfig
from shared.paths import MODELS_DIR


logger = logging.getLogger("services.parser.providers")


class DoclingPipelineDocumentParser:
    def __init__(self, config: DoclingParserConfig):
        self.config = config
        self.converter = None
        self.ready = False

    def start(self) -> None:
        self.converter = self._build_converter()
        self.ready = True

    def stop(self) -> None:
        self.converter = None
        self.ready = False

    def parse_file(self, filepath: str, *, original_filename: str | None = None) -> list[Block]:
        if self.converter is None:
            self.start()
        filename = original_filename or os.path.basename(filepath)
        started = time.perf_counter()
        logger.info("Parser start", extra={"event": "parser_start", "parser": "docling", "document_filename": filename, "ext": Path(filepath).suffix.lower()})
        result = self.converter.convert(filepath)
        blocks = normalize_docling_document(result.document)
        total_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info("Parser done", extra={"event": "parser_done", "parser": "docling", "document_filename": filename, "ext": Path(filepath).suffix.lower(), "block_count": len(blocks), "total_ms": total_ms})
        if not blocks:
            raise InvalidDocumentError(f"Empty file: {filename}")
        return blocks

    def _build_converter(self):
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
        from docling.document_converter import DocumentConverter
        from docling.document_converter import PdfFormatOption

        pipeline_options = PdfPipelineOptions(artifacts_path=MODELS_DIR / "docling")
        pipeline_options.do_formula_enrichment = self.config.formula
        pipeline_options.do_table_structure = self.config.table_enable
        mode = getattr(self.config, "table_mode", "accurate")
        if mode not in {"fast", "accurate"}:
            raise ValueError(f"docling table_mode must be 'fast' or 'accurate', got: {mode!r}")
        pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE if mode == "accurate" else TableFormerMode.FAST
        return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)})
