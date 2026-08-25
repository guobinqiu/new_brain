import re
from html import unescape


def compact_cell_text(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


def split_table(title: str, header: list[str], rows: list[list[str]], chunk_size: int = 1000) -> list[dict]:
    title = title.strip()
    header = [compact_cell_text(cell) for cell in header]
    rows = [[compact_cell_text(cell) for cell in row] for row in rows]
    if not header:
        raise ValueError("table header is required")

    def render(table_rows: list[list[str]]) -> str:
        lines = [title] if title else []
        lines.extend(_render_table_row(header, row) for row in table_rows)
        return "\n".join(line for line in lines if line).strip()

    full_content = render(rows)
    if len(full_content) <= chunk_size:
        return [table_chunk(full_content)]

    chunks = []
    current_rows: list[list[str]] = []
    for row in rows:
        single_row = render([row])
        if len(single_row) > chunk_size:
            if current_rows:
                chunks.append(table_chunk(render(current_rows)))
                current_rows = []
            chunks.append(table_chunk(single_row[:chunk_size]))
            continue

        candidate = current_rows + [row]
        if current_rows and len(render(candidate)) > chunk_size:
            chunks.append(table_chunk(render(current_rows)))
            current_rows = [row]
            continue

        current_rows.append(row)

    if current_rows:
        chunks.append(table_chunk(render(current_rows)))
    return chunks


def table_chunk(content: str) -> dict:
    return {
        "content": content,
        "metadata": {},
    }


def _render_table_row(header: list[str], row: list[str]) -> str:
    pairs = []
    for index, cell in enumerate(row):
        if not cell:
            continue
        key = header[index] if index < len(header) and header[index] else f"列{index + 1}"
        pairs.append(f"{key}: {cell}")
    return "；".join(pairs)
