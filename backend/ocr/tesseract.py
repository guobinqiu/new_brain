from __future__ import annotations

import logging

logger = logging.getLogger("rag.app")


class TesseractOCR:
    def __init__(self, model_dir: str | None = None, langs: tuple[str, ...] = ("eng", "chi_sim")):
        self.model_dir = model_dir
        self.langs = langs
        self._parser = None
        self.ready = False

    def start(self) -> None:
        if self._parser is None:
            logger.info("Loading Tesseract OCR", extra={"event": "ocr_load", "component": "ocr", "ocr": "tesseract", "langs": list(self.langs)})
            self._parser = self._load_parser()
        self.ready = True

    def stop(self) -> None:
        self._parser = None
        self.ready = False

    def image_to_text(self, image_path: str) -> str:
        if not self.ready or self._parser is None:
            raise RuntimeError("ocr is not initialized")

        from langchain_community.document_loaders.blob_loaders import Blob

        blob = Blob.from_path(image_path)
        return "\n".join(doc.page_content for doc in self._parser.lazy_parse(blob))

    def _load_parser(self):
        from langchain_community.document_loaders.parsers.images import TesseractBlobParser

        return TesseractBlobParser(langs=self.langs)
