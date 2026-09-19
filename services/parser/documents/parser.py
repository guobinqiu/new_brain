from pathlib import Path

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

    def supports(self, filename: str) -> bool:
        suffix = Path(filename).suffix.lower()
        return suffix in self.parsers

    def parse_file(self, filepath: str, *, original_filename: str | None = None):
        suffix = Path(original_filename or filepath).suffix.lower()
        return self.parsers[suffix].parse(filepath)
