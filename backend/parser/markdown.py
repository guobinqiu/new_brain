import html
import re

from ocr.base import OCR
from parser.image import expand_image_blocks, parse_markdown_image_blocks
from parser.schema import Block, TextBlock
from parser.table_transform import table_html_to_blocks
from parser.text_splitter import clean_cjk_spaces
from schema import ParserConfig


def parse_markdown_blocks(filepath: str, parser_config: ParserConfig, ocr: OCR | None = None) -> list[Block]:
    blocks: list[Block] = []
    lines = _read_markdown_lines(filepath)
    text_buffer: list[str] = []
    index = 0
    while index < len(lines):
        if _is_table_start(lines, index):
            _flush_text_buffer(blocks, text_buffer)
            table_lines = [lines[index], lines[index + 1]]
            index += 2
            while index < len(lines) and _is_table_row(lines[index]):
                table_lines.append(lines[index])
                index += 1
            blocks.extend(table_html_to_blocks(_table_lines_to_html(table_lines), parser_config))
            continue

        normalized = _normalize_markdown_text_line(lines[index])
        if normalized:
            text_buffer.append(normalized)
        elif text_buffer:
            text_buffer.append("")
        index += 1
    _flush_text_buffer(blocks, text_buffer)
    blocks.extend(parse_markdown_image_blocks(filepath, ocr, parser_config))
    return expand_image_blocks(blocks, parser_config)


def _read_markdown_lines(filepath: str) -> list[str]:
    with open(filepath, encoding="utf-8") as file:
        return file.read().splitlines()


def _flush_text_buffer(blocks: list[Block], text_buffer: list[str]) -> None:
    text = clean_cjk_spaces("\n".join(text_buffer)).strip()
    if text:
        blocks.append(TextBlock(text))
    text_buffer.clear()


def _normalize_markdown_text_line(line: str) -> str:
    line = line.strip()
    if not line:
        return ""
    heading = re.match(r"^#{1,6}\s+(.+?)\s*#*$", line)
    if heading:
        return heading.group(1).strip()
    return line


def _is_table_start(lines: list[str], index: int) -> bool:
    return index + 1 < len(lines) and _is_table_row(lines[index]) and _is_table_separator(lines[index + 1])


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _is_table_separator(line: str) -> bool:
    if not _is_table_row(line):
        return False
    cells = _split_table_row(line)
    return bool(cells) and all(re.match(r"^:?-{3,}:?$", cell.strip()) for cell in cells)


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _table_lines_to_html(lines: list[str]) -> str:
    rows = [_split_table_row(line) for offset, line in enumerate(lines) if offset != 1]
    rendered_rows = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(cell)}</td>" for cell in row)
        rendered_rows.append(f"<tr>{cells}</tr>")
    return "<table>" + "".join(rendered_rows) + "</table>"
