import pytest


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def initialized_ocr():
    from ocr.rapid import RapidOCR

    application = RapidOCR()
    application.start()
    yield application
    application.stop()


class TestOCR:
    """ocr.py – OCR text extraction from images and PDFs."""

    def test_ocr_image_returns_string(self, initialized_ocr, test_img_path):
        """RapidOCR returns a non-empty string."""
        text = initialized_ocr.image_to_text(test_img_path)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_ocr_image_contains_expected_text(self, initialized_ocr, test_img_path):
        """RapidOCR extracts the text we placed in the image."""
        text = initialized_ocr.image_to_text(test_img_path)
        # Should find at least some of the text rendered in the image
        assert (
            "人工智能" in text or "AGI" in text or "test" in text.lower() or "测试" in text
        )


# =============================================================================
# 4. API Endpoint Tests
# =============================================================================
