import uuid

from langchain_community.document_loaders import TextLoader
from schema import ParserConfig

from parser.text_splitter import clean_cjk_spaces, split_text

LOADERS = {
    ".txt": TextLoader,
}


def chunk_text(text: str, filename: str, chunk_size: int = 500, overlap: int = 80) -> list[dict]:
    text = clean_cjk_spaces(text)
    return chunks_to_documents(split_text(text, chunk_size=chunk_size, overlap=overlap), filename)


def load_text_chunks(filepath: str, ext: str, filename: str, parser_config: ParserConfig) -> list[str]:
    text = clean_cjk_spaces(_load_text(filepath, ext, filename))
    if not text.strip():
        raise ValueError(f"Empty file: {filename}")
    return split_text(text, parser_config.chunk_size, parser_config.chunk_overlap)


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


def _load_text(filepath: str, ext: str, filename: str) -> str:
    loader_cls = LOADERS[ext]
    docs = loader_cls(filepath).load()
    if not docs or not docs[0].page_content.strip():
        raise ValueError(f"Empty file: {filename}")
    return "\n".join(doc.page_content for doc in docs)
