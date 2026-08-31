import importlib.util
import logging
import os
import re
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from rag.ocr.base import OCR
from rag.parser.chunker import blocks_to_documents
from rag.parser.schema import Block, TableBlock, TextBlock
from rag.parser.validation import validate_docx_file, validate_image_file, validate_pdf_file, validate_xlsx_file
from rag.schema import UnstructuredParserConfig


logger = logging.getLogger("rag.parser")


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
UNSTRUCTURED_DIR = PROJECT_ROOT / "models" / "unstructured"
UNSTRUCTURED_MODEL_CONFIG = UNSTRUCTURED_DIR / "yolox.json"
HF_CACHE_DIR = PROJECT_ROOT / "models" / "huggingface" / "hub"


class UnstructuredDocumentParser:
    ready = False

    def __init__(self, config: UnstructuredParserConfig, ocr: OCR | None = None):
        self.config = config
        self.ocr = ocr

    def start(self) -> None:
        _prepare_unstructured_runtime_config()
        self.ready = True

    def stop(self) -> None:
        self.ready = False

    def parse_file(self, filepath: str, *, original_filename: str | None = None, ocr: OCR | None = None) -> list[dict]:
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in _SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {ext}")
        _validate_file(filepath, ext)
        filename = original_filename or os.path.basename(filepath)
        started = time.perf_counter()
        logger.info("Parser start", extra={"event": "parser_start", "parser": "unstructured", "document_filename": filename, "ext": ext, "strategy": self.config.strategy, "infer_table_structure": self.config.infer_table_structure})
        blocks = _partition_blocks(filepath, self.config)
        if _should_parse_embedded_images(self.config):
            blocks.extend(_embedded_image_blocks(filepath, ext, self.config))
        chunks = blocks_to_documents(blocks, filename, self.config)
        total_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info("Parser done", extra={"event": "parser_done", "parser": "unstructured", "document_filename": filename, "ext": ext, "strategy": self.config.strategy, "infer_table_structure": self.config.infer_table_structure, "chunk_count": len(chunks), "total_ms": total_ms})
        if not chunks:
            raise ValueError(f"Empty file: {filename}")
        return chunks

    def is_available(self) -> bool:
        return importlib.util.find_spec("unstructured") is not None


_SUPPORTED_EXTENSIONS = {".pdf", ".md", ".docx", ".xlsx", ".txt", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_ARCHIVE_IMAGE_PREFIXES = {
    ".docx": "word/media/",
    ".xlsx": "xl/media/",
}


def _prepare_unstructured_runtime_config() -> None:
    if HF_CACHE_DIR.exists():
        os.environ.setdefault("HF_HOME", str(HF_CACHE_DIR.parent))
        os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(HF_CACHE_DIR))
    if UNSTRUCTURED_MODEL_CONFIG.exists():
        os.environ.setdefault("UNSTRUCTURED_DEFAULT_MODEL_NAME", "yolox")
        os.environ.setdefault("UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH", str(UNSTRUCTURED_MODEL_CONFIG))


def _validate_file(filepath: str, ext: str) -> None:
    if ext == ".pdf":
        validate_pdf_file(filepath)
    elif ext == ".docx":
        validate_docx_file(filepath)
    elif ext == ".xlsx":
        validate_xlsx_file(filepath)
    elif ext in _IMAGE_EXTENSIONS:
        validate_image_file(filepath)


def _partition_blocks(filepath: str, config: UnstructuredParserConfig) -> list[Block]:
    return _elements_to_blocks(_partition_file(filepath, config))


def _partition_file(filepath: str, config: UnstructuredParserConfig):
    try:
        from unstructured.partition.auto import partition
    except ImportError as exc:
        raise RuntimeError("unstructured parser is not installed") from exc
    return partition(
        filename=filepath,
        strategy=config.strategy,
        infer_table_structure=config.infer_table_structure,
        languages=config.languages,
    )


def _should_parse_embedded_images(config: UnstructuredParserConfig) -> bool:
    return config.strategy != "fast" or config.infer_table_structure


def _embedded_image_blocks(filepath: str, ext: str, config: UnstructuredParserConfig) -> list[Block]:
    if ext == ".md":
        return _markdown_image_blocks(filepath, config)
    if ext == ".pdf":
        return _pdf_image_blocks(filepath, config)
    media_prefix = _ARCHIVE_IMAGE_PREFIXES.get(ext)
    if media_prefix is None:
        return []
    return _archive_image_blocks(filepath, media_prefix, config)


def _markdown_image_blocks(filepath: str, config: UnstructuredParserConfig) -> list[Block]:
    markdown = Path(filepath).read_text(encoding="utf-8")
    base_dir = Path(filepath).parent
    blocks: list[Block] = []
    for match in re.finditer(r'!\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)', markdown):
        image_ref = unquote(match.group(1).strip("<>"))
        parsed = urlparse(image_ref)
        if parsed.scheme or parsed.netloc:
            continue
        image_path = (base_dir / image_ref).resolve()
        if image_path.exists():
            blocks.extend(_image_file_blocks(image_path, config))
    return blocks


def _pdf_image_blocks(filepath: str, config: UnstructuredParserConfig) -> list[Block]:
    import fitz

    blocks: list[Block] = []
    with tempfile.TemporaryDirectory(prefix="unstructured_images_") as image_dir:
        root = Path(image_dir)
        doc = fitz.open(filepath)
        try:
            for page in doc:
                for index, img_info in enumerate(page.get_images(full=True)):
                    xref = img_info[0]
                    try:
                        pix = fitz.Pixmap(doc, xref)
                        if pix.n - pix.alpha > 3:
                            pix = fitz.Pixmap(fitz.csRGB, pix)
                        image_path = root / f"page_{page.number}_image_{index}.png"
                        pix.save(str(image_path))
                        blocks.extend(_image_file_blocks(image_path, config))
                    except Exception:
                        continue
        finally:
            doc.close()
    return blocks


def _archive_image_blocks(filepath: str, media_prefix: str, config: UnstructuredParserConfig) -> list[Block]:
    blocks: list[Block] = []
    with tempfile.TemporaryDirectory(prefix="unstructured_images_") as image_dir:
        root = Path(image_dir)
        with zipfile.ZipFile(filepath) as archive:
            for index, name in enumerate(archive.namelist()):
                if not name.startswith(media_prefix):
                    continue
                suffix = os.path.splitext(name)[1].lower()
                if not suffix:
                    continue
                image_path = root / f"embedded_{index}{suffix}"
                image_path.write_bytes(archive.read(name))
                blocks.extend(_image_file_blocks(image_path, config))
    return blocks


def _image_file_blocks(filepath: Path, config: UnstructuredParserConfig) -> list[Block]:
    try:
        validate_image_file(str(filepath))
        return _partition_blocks(str(filepath), config)
    except ValueError:
        return []


def _elements_to_blocks(elements) -> list[Block]:
    blocks: list[Block] = []
    for element in elements:
        text = _element_text(element)
        if not text:
            continue
        if _is_table_element(element):
            blocks.append(TableBlock(text))
        else:
            blocks.append(TextBlock(text))
    return blocks


def _element_text(element) -> str:
    metadata = getattr(element, "metadata", None)
    text_as_html = getattr(metadata, "text_as_html", None) if metadata is not None else None
    if text_as_html and _is_table_element(element):
        return str(text_as_html).strip()
    return str(element).strip()


def _is_table_element(element) -> bool:
    category = getattr(element, "category", None)
    if category == "Table":
        return True
    return element.__class__.__name__ == "Table"
