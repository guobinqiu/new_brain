from services.parser.common.validation import InvalidDocumentError
import logging
import os
import time
from pathlib import Path

from services.parser.common.schema import Block
from services.parser.providers.docling.normalizer import normalize_docling_document
from shared.config import DoclingVlmParserConfig
from shared.paths import MODELS_DIR


logger = logging.getLogger("services.parser.providers")


class DoclingVlmDocumentParser:
    def __init__(self, config: DoclingVlmParserConfig):
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
        logger.info("Parser start", extra={"event": "parser_start", "parser": "docling_vlm", "document_filename": filename, "ext": Path(filepath).suffix.lower()})
        result = self.converter.convert(filepath)
        blocks = normalize_docling_document(result.document)
        total_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info("Parser done", extra={"event": "parser_done", "parser": "docling_vlm", "document_filename": filename, "ext": Path(filepath).suffix.lower(), "block_count": len(blocks), "total_ms": total_ms})
        if not blocks:
            raise InvalidDocumentError(f"Empty file: {filename}")
        return blocks

    def _build_converter(self):
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import VlmPipelineOptions
        from docling.datamodel import vlm_model_specs
        from docling.document_converter import DocumentConverter
        from docling.document_converter import PdfFormatOption
        from docling.pipeline.vlm_pipeline import VlmPipeline

        model_name = (self.config.model or "granitedocling").replace("-", "_").upper()
        if model_name == "GRANITEDOCLING":
            model_name = "GRANITEDOCLING_TRANSFORMERS"
        pipeline_options = VlmPipelineOptions(artifacts_path=MODELS_DIR / "docling")
        try:
            pipeline_options.vlm_options = getattr(vlm_model_specs, model_name)
        except AttributeError as exc:
            raise ValueError(f"Unsupported docling VLM model: {self.config.model}") from exc
        return DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_cls=VlmPipeline,
                    pipeline_options=pipeline_options,
                ),
            },
        )
