from __future__ import annotations

import logging

from config import RAPIDOCR_MODEL_DIR

logger = logging.getLogger("rag.app")


class RapidOCR:
    def __init__(self, model_dir: str | None = RAPIDOCR_MODEL_DIR):
        self.model_dir = model_dir
        self._parser = None
        self._ocr = None
        self.ready = False

    def start(self) -> None:
        if self._parser is None:
            logger.info("Loading RapidOCR", extra={"event": "ocr_load", "component": "ocr", "ocr": "rapidocr", "model_dir": self.model_dir})
            self._parser = self._load_parser()
        self.ready = True

    def stop(self) -> None:
        self._parser = None
        self._ocr = None
        self.ready = False

    def image_to_text(self, image_path: str) -> str:
        if not self.ready or self._parser is None:
            raise RuntimeError("ocr is not initialized")

        from langchain_community.document_loaders.blob_loaders import Blob

        blob = Blob.from_path(image_path)
        return "\n".join(doc.page_content for doc in self._parser.lazy_parse(blob))

    def _load_parser(self):
        from langchain_community.document_loaders.parsers.images import RapidOCRBlobParser

        parser = RapidOCRBlobParser()
        if self.model_dir:
            self._ocr = _load_rapidocr(self.model_dir)
            parser.ocr = self._ocr
        return parser


def _load_rapidocr(model_dir: str):
    from rapidocr import RapidOCR as RapidOCREngine

    params = {"Global": {"model_root_dir": model_dir}}
    try:
        return RapidOCREngine(params=params)
    except ValueError:
        return RapidOCREngine(params={"Global.model_root_dir": model_dir})
