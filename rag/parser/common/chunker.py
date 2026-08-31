import uuid
from typing import Protocol

from rag.parser.common.normalizer import normalize_blocks
from rag.parser.common.schema import Block, TableBlock, TextBlock
from rag.parser.common.text_splitter import split_text
from rag.schema import TableParserConfig, TextParserConfig


class ChunkParserConfig(Protocol):
    text: TextParserConfig
    table: TableParserConfig


def blocks_to_chunks(blocks: list[Block], parser_config: ChunkParserConfig) -> list[str]:
    return [document["content"] for document in blocks_to_documents(blocks, "", parser_config)]


def blocks_to_documents(blocks: list[Block], filename: str, parser_config: ChunkParserConfig) -> list[dict]:
    blocks = normalize_blocks(blocks)
    chunks = []
    text_blocks = []
    for index, block in enumerate(blocks):
        if isinstance(block, TextBlock):
            text_blocks.append(block.text)
            continue
        chunks.extend(_text_blocks_to_documents(text_blocks, filename, parser_config))
        text_blocks = []
        block.header = _table_header(blocks, index, parser_config)
        block.footer = _table_footer(blocks, index, parser_config)
        chunks.append(_document(
            _table_chunk_with_context(block.text, block.header, block.footer),
            filename,
            {},
        ))
    chunks.extend(_text_blocks_to_documents(text_blocks, filename, parser_config))
    for chunk_index, chunk in enumerate(chunks):
        chunk["metadata"]["chunk_index"] = chunk_index
    return chunks


def _text_blocks_to_documents(blocks: list[str], filename: str, parser_config: ChunkParserConfig) -> list[dict]:
    text = "\n".join(block.strip() for block in blocks if block.strip())
    if not text:
        return []
    return [
        _document(chunk.strip(), filename, {})
        for chunk in split_text(text, parser_config.text.chunk_size, parser_config.text.chunk_overlap)
        if chunk.strip()
    ]


def _document(content: str, filename: str, metadata: dict) -> dict:
    document_metadata = dict(metadata)
    if filename:
        document_metadata["filename"] = filename
    return {
        "content": content,
        "metadata": document_metadata,
        "id": str(uuid.uuid4()),
    }


def _table_chunk_with_context(content: str, header: str, footer: str) -> str:
    parts = []
    if header and header not in content:
        parts.append(header)
    parts.append(content)
    if footer and footer not in content:
        parts.append(footer)
    return "\n\n".join(parts)


def _table_header(blocks: list[Block], index: int, parser_config: ChunkParserConfig) -> str:
    if index == 0 or not isinstance(blocks[index - 1], TextBlock):
        return ""
    return _take_backward(blocks[index - 1].text, parser_config.table.header_backward_chars)


def _table_footer(blocks: list[Block], index: int, parser_config: ChunkParserConfig) -> str:
    if index + 1 >= len(blocks) or not isinstance(blocks[index + 1], TextBlock):
        return ""
    next_block = blocks[index + 1]
    return _take_forward(next_block.text, parser_config.table.footer_forward_chars)


def _take_backward(text: str, chars: int) -> str:
    if chars <= 0:
        return ""
    return text.strip()[-chars:]


def _take_forward(text: str, chars: int) -> str:
    if chars <= 0:
        return ""
    return text.strip()[:chars]
