import pytest


pytestmark = pytest.mark.unit


def test_ocr_requires_start_before_use():
    from rag.ocr.rapid import RapidOCR

    application = RapidOCR()

    with pytest.raises(RuntimeError, match="ocr is not initialized"):
        application.image_to_text("image.png")


def test_rapid_ocr_extracts_text_with_langchain_parser():
    from rag.ocr.rapid import RapidOCR

    class FakeDocument:
        page_content = "人工智能\nAGI"

    class FakeParser:
        def lazy_parse(self, blob):
            assert blob.source == "image.png"
            return [FakeDocument()]

    application = RapidOCR()
    application._parser = FakeParser()
    application.ready = True

    assert application.image_to_text("image.png") == "人工智能\nAGI"


def test_ocr_stop_clears_engine():
    from rag.ocr.rapid import RapidOCR

    application = RapidOCR()
    application._parser = object()
    application.ready = True

    application.stop()

    assert application._parser is None
    assert application.ready is False


def test_paddle_ocr_requires_start_before_use():
    from rag.ocr.paddle import PaddleOCR

    application = PaddleOCR()

    with pytest.raises(RuntimeError, match="ocr is not initialized"):
        application.image_to_text("image.png")


def test_paddle_ocr_extracts_result_texts():
    from rag.ocr.paddle import PaddleOCR

    class FakeResult:
        def __init__(self):
            self.json = {"res": {"rec_texts": ["百度", "PaddleOCR"]}}

    class FakeOCR:
        def predict(self, image_path):
            return [FakeResult()]

    application = PaddleOCR()
    application._ocr = FakeOCR()
    application.ready = True

    assert application.image_to_text("image.png") == "百度\nPaddleOCR"


def test_paddle_ocr_logs_loading_message(monkeypatch, caplog):
    from rag.ocr.paddle import PaddleOCR

    monkeypatch.setattr(PaddleOCR, "_load_ocr", lambda self: object())

    application = PaddleOCR(model_dir="/models/PaddlePaddle/PaddleOCR")

    caplog.set_level("INFO", logger="rag.app")
    application.start()

    assert "Loading PaddleOCR" in caplog.text


def test_paddle_ocr_sets_cache_home(monkeypatch):
    import os
    import sys
    import types

    from rag.ocr.paddle import PaddleOCR

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_module = types.SimpleNamespace(PaddleOCR=FakePaddleOCR)
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)
    monkeypatch.delenv("PADDLE_PDX_CACHE_HOME", raising=False)

    PaddleOCR()._load_ocr()

    assert os.environ["PADDLE_PDX_CACHE_HOME"].endswith("models/PaddlePaddle/PaddleOCR")


def test_tesseract_ocr_extracts_text_with_langchain_parser():
    from rag.ocr.tesseract import TesseractOCR

    class FakeDocument:
        page_content = "Tesseract\nOCR"

    class FakeParser:
        def lazy_parse(self, blob):
            assert blob.source == "image.png"
            return [FakeDocument()]

    application = TesseractOCR()
    application._parser = FakeParser()
    application.ready = True

    assert application.image_to_text("image.png") == "Tesseract\nOCR"


def test_tesseract_ocr_logs_loading_message(monkeypatch, caplog):
    from rag.ocr.tesseract import TesseractOCR

    monkeypatch.setattr(TesseractOCR, "_load_parser", lambda self: object())

    application = TesseractOCR(langs=("eng", "chi_sim"))

    caplog.set_level("INFO", logger="rag.app")
    application.start()

    assert "Loading Tesseract OCR" in caplog.text
