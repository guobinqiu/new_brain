import uuid

from parser.normalizer import normalize_blocks
from parser.schema import Block, ImageBlock, TableBlock, TextBlock
from parser.text_splitter import split_text
from schema import ParserConfig


def blocks_to_chunks(blocks: list[Block], parser_config: ParserConfig) -> list[str]:
    return [document["content"] for document in blocks_to_documents(blocks, "", parser_config)]


def blocks_to_documents(blocks: list[Block], filename: str, parser_config: ParserConfig) -> list[dict]:
    blocks = normalize_blocks(blocks)
    chunks = []
    table_ids = _table_ids(blocks)
    text_blocks = []
    for index, block in enumerate(blocks):
        if isinstance(block, TextBlock):
            text_blocks.append(block.text)
            continue
        if isinstance(block, ImageBlock):
            text_blocks.append(block.text)
            continue
        chunks.extend(_text_blocks_to_documents(text_blocks, filename, parser_config))
        text_blocks = []
        block.before = _before_table(blocks, index, parser_config)
        block.after = _after_table(blocks, index, parser_config)
        chunks.append(_document(
            _table_chunk_with_context(block.text, block.before, block.after),
            filename,
            {
                "content_type": "table",
                "table_id": table_ids[block.table_key],
                "table_part_index": block.table_part_index,
                "table_part_count": block.table_part_count,
            },
        ))
    chunks.extend(_text_blocks_to_documents(text_blocks, filename, parser_config))
    for chunk_index, chunk in enumerate(chunks):
        chunk["metadata"]["chunk_index"] = chunk_index
    return chunks


def _text_blocks_to_documents(blocks: list[str], filename: str, parser_config: ParserConfig) -> list[dict]:
    text = "\n".join(block.strip() for block in blocks if block.strip())
    if not text:
        return []
    return [
        _document(chunk.strip(), filename, {"content_type": "text"})
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


def _table_ids(blocks: list[Block]) -> dict[object, str]:
    ids = {}
    for block in blocks:
        if isinstance(block, TableBlock) and block.table_key not in ids:
            ids[block.table_key] = f"table_{len(ids) + 1}"
    return ids


def _table_chunk_with_context(content: str, before: str, after: str) -> str:
    parts = []
    if before and before not in content:
        parts.append(before)
    parts.append(content)
    if after and after not in content:
        parts.append(after)
    return "\n\n".join(parts)


def _limit_text(text: str, limit: int, *, head: bool) -> str:
    text = text.strip()
    if not text or limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] if head else text[-limit:]


def _before_table(blocks: list[Block], index: int, parser_config: ParserConfig) -> str:
    if index == 0 or not isinstance(blocks[index - 1], TextBlock):
        return ""
    return _limit_text(blocks[index - 1].text, parser_config.table.before_text_size, head=False)


def _after_table(blocks: list[Block], index: int, parser_config: ParserConfig) -> str:
    if index + 1 >= len(blocks) or not isinstance(blocks[index + 1], TextBlock):
        return ""
    next_block = blocks[index + 1]
    if next_block.kind == "section_title":
        return ""
    return _limit_text(next_block.text, parser_config.table.after_text_size, head=True)
