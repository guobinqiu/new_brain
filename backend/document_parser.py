import re
import os
import tempfile
import unicodedata
import uuid

from langchain_community.document_loaders import TextLoader, Docx2txtLoader, UnstructuredMarkdownLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from ocr.base import OCR

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

LOADERS = {
    ".txt": TextLoader,
    ".md": UnstructuredMarkdownLoader,
    ".markdown": UnstructuredMarkdownLoader,
    ".docx": Docx2txtLoader,
}

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=250,
    chunk_overlap=50,
    separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
    keep_separator=False,
)


def _clean_cjk_spaces(text: str) -> str:
    """归一化 Unicode（康熙部首 → 标准汉字）并去除
    中文字符之间的空格（PDF 提取产物）。"""
    text = unicodedata.normalize('NFKC', text)
    return re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])', '', text)


def parse_file(filepath: str, original_filename: str | None = None, ocr: OCR | None = None) -> list[dict]:
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in LOADERS and ext not in IMAGE_EXTS and ext != ".pdf":
        raise ValueError(f"Unsupported file type: {ext}")
    filename = original_filename or os.path.basename(filepath)

    if ext == ".pdf":
        import fitz
        doc = fitz.open(filepath)
        parts = []
        for page in doc:
            page_text = page.get_text()
            # 提取该页内嵌图片并 OCR
            img_texts = []
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.n - pix.alpha > 3:  # CMYK 转换
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                    try:
                        pix.save(tmp.name)
                        if ocr is None:
                            continue
                        t = ocr.image_to_text(tmp.name)
                        if t.strip():
                            img_texts.append(t)
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
        text = "\n".join(parts)
    elif ext in IMAGE_EXTS:
        if ocr is None:
            raise RuntimeError("ocr is required for image parsing")
        text = ocr.image_to_text(filepath)
    else:
        loader_cls = LOADERS[ext]
        docs = loader_cls(filepath).load()
        if not docs or not docs[0].page_content.strip():
            raise ValueError(f"Empty file: {filename}")
        text = "\n".join(d.page_content for d in docs)

    text = _clean_cjk_spaces(text)
    if not text.strip():
        raise ValueError(f"Empty file: {filename}")

    chunks = _splitter.split_text(text)

    results = []
    for i, chunk_text in enumerate(chunks):
        chunk_text = chunk_text.strip()
        if not chunk_text:
            continue
        results.append({
            "content": chunk_text,
            "metadata": {
                "filename": filename,
                "chunk_index": i,
            },
            "id": f"{filename}_{i}_{uuid.uuid4().hex[:8]}",
        })
    return results


def chunk_text(text: str, filename: str, chunk_size: int = 250, overlap: int = 50) -> list[dict]:
    """为测试兼容保留的辅助函数。包装 LangChain splitter。"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
        keep_separator=False,
    )
    text = _clean_cjk_spaces(text)
    chunks = splitter.split_text(text)
    results = []
    for i, ct in enumerate(chunks):
        ct = ct.strip()
        if not ct:
            continue
        results.append({
            "content": ct,
            "metadata": {
                "filename": filename,
                "chunk_index": i,
            },
            "id": f"{filename}_{i}_{uuid.uuid4().hex[:8]}",
        })
    return results
