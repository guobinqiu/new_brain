import re
from html import unescape


def compact_cell_text(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


def split_table(title: str, header: list[str], rows: list[list[str]]) -> list[dict]:
    title = title.strip()
    header = [compact_cell_text(cell) for cell in header]
    rows = [[compact_cell_text(cell) for cell in row] for row in rows]
    if not header:
        raise ValueError("table header is required")

    def render(table_rows: list[list[str]]) -> str:
        lines = [title] if title else []
        lines.extend(_render_markdown_header(header))
        lines.extend(_render_table_row(header, row) for row in table_rows)
        return "\n".join(line for line in lines if line).strip()

    full_content = render(rows)
    return [table_chunk(full_content)]


def table_chunk(content: str) -> dict:
    return {
        "content": content,
        "metadata": {},
    }


def _render_table_row(header: list[str], row: list[str]) -> str:
    cells = []
    width = max(len(header), len(row))
    for index in range(width):
        cell = row[index] if index < len(row) else ""
        cells.append(_escape_markdown_cell(cell))
    return "| " + " | ".join(cells) + " |"


def _render_markdown_header(header: list[str]) -> list[str]:
    width = max(1, len(header))
    header_cells = [_escape_markdown_cell(header[index] if index < len(header) and header[index] else f"列{index + 1}") for index in range(width)]
    separator_cells = ["---"] * width
    return [
        "| " + " | ".join(header_cells) + " |",
        "| " + " | ".join(separator_cells) + " |",
    ]


def _escape_markdown_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
