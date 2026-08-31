import uuid

from langchain_community.document_loaders import TextLoader
from rag.ocr.base import OCR
from rag.parser.base import BlockParser
from rag.parser.schema import Block, TextBlock
from rag.parser.text_splitter import clean_cjk_spaces, split_text

LOADERS = {
    ".txt": TextLoader,
}


def chunk_text(text: str, filename: str, chunk_size: int = 500, overlap: int = 80) -> list[dict]:
    text = clean_cjk_spaces(text)
    return chunks_to_documents(split_text(text, chunk_size=chunk_size, overlap=overlap), filename)


class TextBlockParser(BlockParser):
    def parse(self, filepath: str, ocr: OCR | None = None) -> list[Block]:
        ext = ".txt"
        filename = filepath.rsplit("/", 1)[-1]
        text = clean_cjk_spaces(self._load_text(filepath, ext, filename))
        if not text.strip():
            raise ValueError(f"Empty file: {filename}")
        chunks = split_text(text, self.parser_config.text.chunk_size, self.parser_config.text.chunk_overlap)
        return [TextBlock(text) for text in chunks]

    def _load_text(self, filepath: str, ext: str, filename: str) -> str:
        loader_cls = LOADERS[ext]
        docs = loader_cls(filepath).load()
        if not docs or not docs[0].page_content.strip():
            raise ValueError(f"Empty file: {filename}")
        return "\n".join(doc.page_content for doc in docs)


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

