import os
import tempfile
import uuid

from langchain_community.document_loaders import TextLoader, Docx2txtLoader, UnstructuredMarkdownLoader
from ocr.base import OCR
from schema import ParserConfig

from parser.text_splitter import clean_cjk_spaces, split_text


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

LOADERS = {
    ".txt": TextLoader,
    ".md": UnstructuredMarkdownLoader,
    ".markdown": UnstructuredMarkdownLoader,
    ".docx": Docx2txtLoader,
}


class TextParser:
    ready = False

    def __init__(self, config: ParserConfig, ocr: OCR | None = None):
        self.config = config
        self.ocr = ocr

    def start(self) -> None:
        self.ready = True

    def stop(self) -> None:
        self.ready = False

    def parse_file(self, filepath: str, *, original_filename: str | None = None, ocr: OCR | None = None, parser_type: str | None = None) -> list[dict]:
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in LOADERS and ext not in IMAGE_EXTS and ext != ".pdf":
            raise ValueError(f"Unsupported file type: {ext}")
        filename = original_filename or os.path.basename(filepath)

        if ext == ".pdf":
            text = _parse_pdf_text(filepath, filename, ocr or self.ocr)
        elif ext in IMAGE_EXTS:
            parser_ocr = ocr or self.ocr
            if parser_ocr is None:
                raise RuntimeError("ocr is required for image parsing")
            text = parser_ocr.image_to_text(filepath)
        else:
            text = _load_text(filepath, ext, filename)

        text = clean_cjk_spaces(text)
        if not text.strip():
            raise ValueError(f"Empty file: {filename}")

        return chunks_to_documents(
            split_text(text, self.config.text.chunk_size, self.config.text.chunk_overlap),
            filename,
        )


def chunk_text(text: str, filename: str, chunk_size: int = 500, overlap: int = 80) -> list[dict]:
    text = clean_cjk_spaces(text)
    return chunks_to_documents(split_text(text, chunk_size=chunk_size, overlap=overlap), filename)


def chunks_to_documents(chunks: list[str], filename: str) -> list[dict]:
    results = []
    for chunk_index, chunk_text in enumerate(chunks):
        chunk_text = chunk_text.strip()
        if not chunk_text:
            continue
        results.append({
            "content": chunk_text,
            "metadata": {
                "filename": filename,
                "chunk_index": chunk_index,
            },
            "id": str(uuid.uuid4()),
        })
    return results


def _parse_pdf_text(filepath: str, filename: str, ocr: OCR | None) -> str:
    import fitz

    doc = fitz.open(filepath)
    parts = []
    for page in doc:
        page_text = page.get_text()
        img_texts = []
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.n - pix.alpha > 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                try:
                    pix.save(tmp.name)
                    if ocr is None:
                        continue
                    text = ocr.image_to_text(tmp.name)
                    if text.strip():
                        img_texts.append(text)
                finally:
                    os.unlink(tmp.name)
            except Exception:
                continue
        page_content = page_text
        if img_texts:
            page_content += "\n[图片文字]\n" + "\n".join(img_texts)
        if page_content.strip():
            parts.append(page_content)
    doc.close()
    if not parts:
        raise ValueError(f"Empty file: {filename}")
    return "\n".join(parts)


def _load_text(filepath: str, ext: str, filename: str) -> str:
    loader_cls = LOADERS[ext]
    docs = loader_cls(filepath).load()
    if not docs or not docs[0].page_content.strip():
        raise ValueError(f"Empty file: {filename}")
    return "\n".join(doc.page_content for doc in docs)
