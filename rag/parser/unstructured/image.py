import os
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from rag.ocr.base import OCR
from rag.parser.common.base import BlockParser
from rag.parser.common.schema import Block
from rag.parser.common.validation import validate_image_file
from rag.parser.unstructured.blocks import partition_blocks


class ImageBlockParser(BlockParser):
    def parse(self, filepath: str, ocr: OCR | None = None) -> list[Block]:
        validate_image_file(filepath)
        return partition_blocks(filepath, self.parser_config)

    def parse_markdown_image_blocks(self, filepath: str, ocr: OCR | None = None) -> list[Block]:
        markdown = Path(filepath).read_text(encoding="utf-8")
        base_dir = Path(filepath).parent
        blocks: list[Block] = []
        for match in re.finditer(r'!\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)', markdown):
            image_ref = unquote(match.group(1).strip("<>"))
            parsed = urlparse(image_ref)
            if parsed.scheme or parsed.netloc:
                continue
            image_path = (base_dir / image_ref).resolve()
            if image_path.exists():
                blocks.extend(self._safe_parse_image_file(image_path, ocr))
        return blocks

    def parse_embedded_image_blocks(self, filepath: str, media_prefix: str, image_dir: Path, ocr: OCR | None = None) -> list[Block]:
        blocks: list[Block] = []
        with zipfile.ZipFile(filepath) as archive:
            for index, name in enumerate(archive.namelist()):
                if not name.startswith(media_prefix):
                    continue
                suffix = os.path.splitext(name)[1].lower()
                if not suffix:
                    continue
                image_path = image_dir / f"embedded_{index}{suffix}"
                image_path.write_bytes(archive.read(name))
                blocks.extend(self._safe_parse_image_file(image_path, ocr))
        return blocks

    def _safe_parse_image_file(self, filepath: Path, ocr: OCR | None) -> list[Block]:
        try:
            return self.parse(str(filepath), ocr)
        except ValueError:
            return []
