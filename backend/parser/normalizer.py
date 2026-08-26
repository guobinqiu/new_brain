import re

from parser.schema import Block, TextBlock


def normalize_blocks(blocks: list[Block]) -> list[Block]:
    normalized: list[Block] = []
    text_buffer: list[str] = []

    def flush_text() -> None:
        if not text_buffer:
            return
        text = "\n".join(text_buffer).strip()
        text_buffer.clear()
        if text:
            normalized.append(TextBlock(text))

    for block in blocks:
        if isinstance(block, TextBlock):
            text = block.text.strip()
            if not text:
                continue
            if is_section_title_text(text):
                flush_text()
                normalized.append(TextBlock(text, kind="section_title"))
                continue
            text_buffer.append(text)
            continue

        flush_text()
        normalized.append(block)

    flush_text()
    return normalized


def is_section_title_text(text: str) -> bool:
    text = text.strip()
    if "\n" in text or len(text) > 80:
        return False
    return bool(re.match(r"^(\d+[\.\、]|[一二三四五六七八九十]+[、.．]|[A-Z][\).])\s*\S+", text))
