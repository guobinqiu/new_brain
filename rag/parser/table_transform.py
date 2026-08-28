import json
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from rag.parser.chunker import blocks_to_chunks, blocks_to_documents
from rag.parser.normalizer import is_section_title_text
from rag.parser.schema import Block, TableBlock, TextBlock
from rag.parser.table_splitter import compact_cell_text, split_table
from rag.schema import ParserConfig


def read_table_chunks(output_dir: Path, parser_config: ParserConfig) -> list[str]:
    chunks = _read_content_list(output_dir, parser_config)
    if chunks is not None:
        return chunks
    raise ValueError("table parser output json not found")


def read_table_documents(output_dir: Path, filename: str, parser_config: ParserConfig) -> list[dict]:
    documents = _read_content_list_documents(output_dir, filename, parser_config)
    if documents is not None:
        return documents
    raise ValueError("table parser output json not found")


def read_table_blocks(output_dir: Path, parser_config: ParserConfig) -> list[Block]:
    blocks = _read_content_list_blocks(output_dir, parser_config)
    if blocks is not None:
        return blocks
    raise ValueError("table parser output json not found")


def html_table_to_rows(html: str) -> list[list[str]]:
    parser = _HTMLTableParser()
    parser.feed(html)
    if not parser.rows:
        return []

    width = max(len(row) for row in parser.rows)
    rows = [row + [""] * (width - len(row)) for row in parser.rows]
    non_empty_columns = [index for index in range(width) if any(row[index] for row in rows)]
    if non_empty_columns:
        rows = [[row[index] for index in non_empty_columns] for row in rows]
    return rows


def table_html_to_chunks(html: str, parser_config: ParserConfig, title: str = "") -> list[str]:
    return _table_rows_to_chunks(title, html_table_to_rows(html), parser_config)


def table_html_to_blocks(html: str, parser_config: ParserConfig, title: str = "") -> list[Block]:
    return _table_rows_to_blocks(title, html_table_to_rows(html), parser_config)


def strip_html_tags(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text)


def clean_table_text(text: str) -> str:
    return re.sub(r"(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])", "", text)


def _read_content_list(output_dir: Path, parser_config: ParserConfig) -> list[str] | None:
    documents = _read_content_list_documents(output_dir, "", parser_config)
    if documents is None:
        return None
    return [document["content"] for document in documents]


def _read_content_list_documents(output_dir: Path, filename: str, parser_config: ParserConfig) -> list[dict] | None:
    blocks = _read_content_list_blocks(output_dir, parser_config)
    if blocks is None:
        return None
    return blocks_to_documents(blocks, filename, parser_config)


def _read_content_list_blocks(output_dir: Path, parser_config: ParserConfig) -> list[Block] | None:
    json_files = sorted(output_dir.rglob("*_content_list.json"))
    for path in json_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        blocks = _content_list_to_blocks(data, parser_config)
        if blocks:
            return blocks
    return None


def _content_list_to_chunks(data, parser_config: ParserConfig) -> list[str]:
    return [document["content"] for document in _content_list_to_documents(data, "", parser_config)]


def _content_list_to_documents(data, filename: str, parser_config: ParserConfig) -> list[dict]:
    return blocks_to_documents(_content_list_to_blocks(data, parser_config), filename, parser_config)


def _content_list_to_blocks(data, parser_config: ParserConfig) -> list[Block]:
    if not isinstance(data, list):
        return []
    blocks = []
    for item in data:
        if not isinstance(item, dict):
            continue
        blocks.extend(_content_item_to_blocks(item, parser_config))
    return blocks


def _content_item_to_blocks(item: dict, parser_config: ParserConfig) -> list[Block]:
    item_type = item.get("type")
    if item_type == "table":
        return _table_item_to_blocks(item, _text_value(item.get("table_caption")), parser_config)
    if item_type == "image":
        text = _text_value(item.get("img_caption"))
    else:
        text = _text_value(item.get("text") or item.get("content"))
    text = clean_table_text(text)
    if not text:
        return []
    return [TextBlock(text)]


def _table_item_to_blocks(item: dict, caption: str, parser_config: ParserConfig) -> list[Block]:
    table_body = item.get("table_body") or item.get("html")
    if isinstance(table_body, str) and table_body.strip():
        return _table_rows_to_blocks(caption, html_table_to_rows(table_body), parser_config)
    rows = item.get("rows")
    if not isinstance(rows, list):
        return []
    normalized_rows = []
    for row in rows:
        if isinstance(row, list):
            normalized_rows.append([compact_cell_text(str(cell)) for cell in row])
    return _table_rows_to_blocks(caption, normalized_rows, parser_config)


def _table_rows_to_chunks(title: str, rows: list[list[str]], parser_config: ParserConfig) -> list[str]:
    return blocks_to_chunks(_table_rows_to_blocks(title, rows, parser_config), parser_config)


def _table_rows_to_blocks(title: str, rows: list[list[str]], parser_config: ParserConfig) -> list[Block]:
    if not rows:
        return []
    blocks = []
    for block_type, logical_title, header, body in _split_logical_tables(title, rows):
        if block_type == "text":
            text = clean_table_text(logical_title).strip()
            if text:
                blocks.append(TextBlock(text))
            continue
        table_chunks = split_table(logical_title, header, body)
        for chunk in table_chunks:
            content = clean_table_text(chunk["content"]).strip()
            if content:
                blocks.append(TableBlock(content))
    return blocks


def _split_logical_tables(title: str, rows: list[list[str]]) -> list[tuple[str, str, list[str], list[list[str]]]]:
    if len(rows) >= 2 and _is_section_title_row(rows[0]):
        title = "\n".join(part for part in (title, _row_text(rows[0])) if part)
        rows = rows[1:]

    header = rows[0]
    body = rows[1:]
    if not body:
        return [("table", title, [f"列{index + 1}" for index in range(len(header))], [header])]

    tables: list[tuple[str, str, list[str], list[list[str]]]] = []
    current_title = title
    current_header = header
    current_rows: list[list[str]] = []
    index = 0
    while index < len(body):
        row = body[index]
        next_row = body[index + 1] if index + 1 < len(body) else None
        if current_rows and _is_section_title_row(row) and next_row is not None and _is_header_row(next_row):
            tables.append(("table", current_title, current_header, current_rows))
            tables.append(("text", _row_text(row), [], []))
            current_title = ""
            current_header = next_row
            current_rows = []
            index += 2
            continue
        current_rows.append(row)
        index += 1

    if current_rows:
        tables.append(("table", current_title, current_header, current_rows))
    return tables


def _is_section_title_row(row: list[str]) -> bool:
    cells = [cell for cell in row if cell.strip()]
    if len(cells) != 1:
        return False
    return _is_section_title_text(cells[0])


def _is_section_title_text(text: str) -> bool:
    return is_section_title_text(text)


def _is_header_row(row: list[str]) -> bool:
    return sum(1 for cell in row if cell.strip()) >= 2


def _row_text(row: list[str]) -> str:
    return " ".join(cell.strip() for cell in row if cell.strip())


def _text_value(value) -> str:
    if isinstance(value, str):
        return strip_html_tags(value).strip()
    if isinstance(value, list):
        return " ".join(_text_value(item) for item in value if item).strip()
    return ""


class _HTMLTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(compact_cell_text("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(cell for cell in self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
