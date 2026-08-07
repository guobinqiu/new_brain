from __future__ import annotations

from pathlib import Path
from typing import Any

from config import PADDLEOCR_MODEL_DIR


class PaddleOCR:
    def __init__(self, model_dir: str = PADDLEOCR_MODEL_DIR):
        self.model_dir = model_dir
        self._ocr = None
        self.ready = False

    def start(self) -> None:
        if self._ocr is None:
            print(f"Loading PaddleOCR: {self.model_dir} ...")
            self._ocr = self._load_ocr()
        self.ready = True

    def stop(self) -> None:
        self._ocr = None
        self.ready = False

    def image_to_text(self, image_path: str) -> str:
        if not self.ready or self._ocr is None:
            raise RuntimeError("ocr is not initialized")

        result = self._predict(image_path)
        return "\n".join(_extract_texts(result))

    def _load_ocr(self):
        from paddleocr import PaddleOCR as PaddleEngine

        kwargs = {
            "lang": "ch",
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
        }
        kwargs.update(_model_kwargs(self.model_dir))
        try:
            return PaddleEngine(**kwargs)
        except TypeError:
            legacy_kwargs = {
                "lang": "ch",
                "use_angle_cls": False,
                "show_log": False,
            }
            legacy_kwargs.update(_legacy_model_kwargs(self.model_dir))
            return PaddleEngine(**legacy_kwargs)

    def _predict(self, image_path: str):
        predict = getattr(self._ocr, "predict", None)
        if callable(predict):
            return predict(image_path)
        ocr = getattr(self._ocr, "ocr", None)
        if callable(ocr):
            return ocr(image_path, cls=False)
        return self._ocr(image_path)


def _model_kwargs(model_dir: str) -> dict[str, str]:
    root = Path(model_dir)
    mapping = {
        "det": "text_detection_model_dir",
        "rec": "text_recognition_model_dir",
    }
    return {
        arg_name: str(root / child)
        for child, arg_name in mapping.items()
        if (root / child).exists()
    }


def _legacy_model_kwargs(model_dir: str) -> dict[str, str]:
    root = Path(model_dir)
    mapping = {
        "det": "det_model_dir",
        "rec": "rec_model_dir",
        "cls": "cls_model_dir",
    }
    return {
        arg_name: str(root / child)
        for child, arg_name in mapping.items()
        if (root / child).exists()
    }


def _extract_texts(result: Any) -> list[str]:
    texts: list[str] = []
    _collect_texts(result, texts)
    return texts


def _collect_texts(value: Any, texts: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, dict):
        rec_texts = value.get("rec_texts")
        if isinstance(rec_texts, list):
            texts.extend(str(text) for text in rec_texts)
            return
        for child in value.values():
            _collect_texts(child, texts)
        return
    json_value = getattr(value, "json", None)
    if isinstance(json_value, dict):
        _collect_texts(json_value, texts)
        return
    if isinstance(value, (list, tuple)):
        if len(value) >= 2 and isinstance(value[1], tuple) and value[1]:
            texts.append(str(value[1][0]))
            return
        for child in value:
            _collect_texts(child, texts)
