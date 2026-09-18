from pathlib import Path

from services.parser.common.office_convert import convert_legacy_office_file
from services.parser.documents.docx import DocxBlockParser
from services.parser.documents.xlsx import XlsxBlockParser
from services.parser.documents.md import MdBlockParser
from services.parser.documents.pptx import PptxBlockParser
from services.parser.documents.txt import TxtBlockParser


class DocumentParser:
    def __init__(self):
        self.parsers = {
            ".txt": TxtBlockParser(),
            ".md": MdBlockParser(),
            ".docx": DocxBlockParser(),
            ".xlsx": XlsxBlockParser(),
            ".pptx": PptxBlockParser(),
        }
        self.legacy_formats = {".doc": ".docx", ".xls": ".xlsx", ".ppt": ".pptx"}

    def supports(self, filename: str) -> bool:
        suffix = Path(filename).suffix.lower()
        return suffix in self.parsers or suffix in self.legacy_formats

    def parse_file(self, filepath: str, *, original_filename: str | None = None):
        suffix = Path(original_filename or filepath).suffix.lower()
        if suffix in self.legacy_formats:
            target = self.legacy_formats[suffix]
            with convert_legacy_office_file(filepath, target) as converted:
                return self.parsers[target].parse(str(converted))
        return self.parsers[suffix].parse(filepath)
