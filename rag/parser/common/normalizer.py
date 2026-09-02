import re

from rag.parser.common.schema import Block, TextBlock


def normalize_blocks(blocks: list[Block]) -> list[Block]:
    normalized: list[Block] = []

    for block in blocks:
        if isinstance(block, TextBlock):
            text = block.text.strip()
            if not text:
                continue
            if is_section_title_text(text):
                normalized.append(TextBlock(text, kind="section_title"))
                continue
            normalized.append(TextBlock(text, kind=block.kind))
            continue

        normalized.append(block)

    return normalized


def is_section_title_text(text: str) -> bool:
    text = text.strip()
    if "\n" in text or len(text) > 80:
        return False
    return bool(re.match(r"^(\d+[\.\、]|[一二三四五六七八九十]+[、.．]|[A-Z][\).])\s*\S+", text))
