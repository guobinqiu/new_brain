import json
from pathlib import Path

from services.parser.common.cleaner import clean_parser_blocks
from services.parser.common.schema import Block, FormulaBlock, TextBlock
from services.parser.common.table_blocks import clean_table_text, compact_cell_text, html_table_to_rows, strip_html_tags, table_rows_to_blocks


def read_content_list_blocks(output_dir: Path) -> list[Block]:
    json_files = sorted(output_dir.rglob("*_content_list.json"))
    for path in json_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        blocks = content_list_to_blocks(data)
        if blocks:
            return blocks
    return []


def content_list_to_blocks(data) -> list[Block]:
    if not isinstance(data, list):
        return []
    blocks = []
    for item in data:
        if not isinstance(item, dict):
            continue
        blocks.extend(_content_item_to_blocks(item))
    return clean_parser_blocks(blocks)


def _content_item_to_blocks(item: dict) -> list[Block]:
    item_type = item.get("type")
    if item_type == "table":
        return _table_item_to_blocks(item, _text_value(item.get("table_caption")))
    if item_type in {"image", "chart"}:
        return []
    if item_type == "list":
        return [TextBlock(text.strip(), page=_mineru_page(item), kind="list_item")
                for text in item.get("list_items", []) if text.strip()]
    if item_type == "code":
        text = str(item.get("code_body") or "").rstrip("\r\n")
        return [TextBlock(text, page=_mineru_page(item), kind="code")] if text.strip() else []
    if item_type in {"equation", "interline_equation"}:
        text = clean_table_text(_text_value(item.get("text") or item.get("content")))
        return [FormulaBlock(text, format=str(item.get("text_format") or "latex"), page=_mineru_page(item))] if text else []

    text = clean_table_text(_text_value(item.get("text") or item.get("content")))
    if not text:
        return []
    kind = "heading" if item.get("text_level") else "text"
    return [TextBlock(text, page=_mineru_page(item), kind=kind)]


def _table_item_to_blocks(item: dict, caption: str) -> list[Block]:
    table_body = item.get("table_body") or item.get("html")
    if isinstance(table_body, str) and table_body.strip():
        return table_rows_to_blocks(caption, html_table_to_rows(table_body), page=_mineru_page(item))
    rows = item.get("rows")
    if not isinstance(rows, list):
        return []
    normalized_rows = []
    for row in rows:
        if isinstance(row, list):
            normalized_rows.append([compact_cell_text(str(cell)) for cell in row])
    return table_rows_to_blocks(caption, normalized_rows, page=_mineru_page(item))


def _mineru_page(item: dict) -> int | None:
    page_idx = item.get("page_idx")
    return int(page_idx) + 1 if page_idx is not None else None


def _text_value(value) -> str:
    if isinstance(value, str):
        return strip_html_tags(value).strip()
    if isinstance(value, list):
        return " ".join(_text_value(item) for item in value if item).strip()
    return ""
