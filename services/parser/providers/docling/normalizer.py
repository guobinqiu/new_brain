from __future__ import annotations

from services.parser.common.cleaner import clean_parser_blocks
from services.parser.common.schema import Block, FormulaBlock, TableBlock, TextBlock
from services.parser.common.table_blocks import compact_cell_text


def normalize_docling_document(document) -> list[Block]:
    data = document.export_to_dict()
    refs = _build_ref_index(data)
    table_caption_refs = {
        caption["$ref"]
        for table in data.get("tables", [])
        for caption in table.get("captions", [])
    }
    blocks: list[Block] = []
    for child in data.get("body", {}).get("children", []):
        blocks.extend(_blocks_from_ref(child.get("$ref"), refs, table_caption_refs))
    return clean_parser_blocks(blocks)


def _build_ref_index(data: dict) -> dict[str, dict]:
    refs = {}
    for key in ("texts", "tables", "pictures", "groups"):
        for item in data.get(key, []):
            if isinstance(item, dict) and item.get("self_ref"):
                refs[item["self_ref"]] = item
    return refs


def _blocks_from_ref(ref: str | None, refs: dict[str, dict], table_caption_refs: set[str]) -> list[Block]:
    if not ref or ref in table_caption_refs:
        return []
    item = refs.get(ref)
    if not item:
        return []
    if ref.startswith("#/groups/"):
        blocks: list[Block] = []
        for child in item.get("children", []):
            blocks.extend(_blocks_from_ref(child.get("$ref"), refs, table_caption_refs))
        return blocks
    if ref.startswith("#/texts/"):
        return _text_item_to_blocks(item)
    if ref.startswith("#/tables/"):
        block = _table_item_to_block(item, refs)
        return [block] if block is not None else []
    return []


def _text_item_to_blocks(item: dict) -> list[Block]:
    label = str(item.get("label") or "text")
    raw_text = str(item.get("text") or "")
    text = raw_text if label == "code" else compact_cell_text(raw_text)
    if not text.strip():
        return []
    page = _page(item)
    if label == "formula":
        return [FormulaBlock(text, page=page)]
    kind = {"title": "heading", "section_header": "heading", "paragraph": "paragraph",
            "list_item": "list_item", "code": "code"}.get(label, "text")
    return [TextBlock(text, page=page, kind=kind)]


def _table_item_to_block(item: dict, refs: dict[str, dict]) -> TableBlock | None:
    data = item.get("data") or {}
    rows = _table_rows(data)
    if not rows:
        return None
    caption = compact_cell_text("".join(refs[caption["$ref"]]["text"] for caption in item.get("captions", [])))
    return TableBlock(rows=rows, caption=caption, page=_page(item))


def _table_rows(data: dict) -> list[list[str]]:
    row_count = int(data.get("num_rows") or 0)
    col_count = int(data.get("num_cols") or 0)
    if row_count <= 0 or col_count <= 0:
        return []
    rows = [["" for _ in range(col_count)] for _ in range(row_count)]
    for cell in data.get("table_cells", []):
        row_index = int(cell.get("start_row_offset_idx") or 0)
        col_index = int(cell.get("start_col_offset_idx") or 0)
        if row_index < row_count and col_index < col_count:
            rows[row_index][col_index] = compact_cell_text(str(cell.get("text") or ""))
    return rows


def _page(item: dict) -> int | None:
    prov = item.get("prov") or []
    if not prov:
        return None
    page = prov[0].get("page_no")
    return int(page) if page is not None else None
