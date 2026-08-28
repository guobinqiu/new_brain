from rag.ocr.base import OCR
from rag.ocr.paddle import PaddleOCR
from rag.ocr.rapid import RapidOCR
from rag.ocr.tesseract import TesseractOCR

__all__ = ["OCR", "PaddleOCR", "RapidOCR", "TesseractOCR"]
