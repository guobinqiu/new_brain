import os

import pytest


pytestmark = pytest.mark.integration


class TestModelPaths:
    """config.py / ocr.py - model paths resolved under the project models/ dir.

    Guards the refactor that moved the dense model, reranker and OCR
    models from ~/.cache/huggingface into a project-local ``models/``
    directory managed by ``config.py`` constants.
    """

    def test_models_dir_points_to_project_models(self):
        """MODELS_DIR points to <project>/models directory."""
        import config as cf

        expected = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            "models",
        )
        assert cf.MODELS_DIR == expected

    def test_model_subdirs_exist(self):
        """Model dirs live under MODELS_DIR with correct names."""
        import config as cf

        assert cf.DENSE_MODEL_DIR.startswith(cf.MODELS_DIR)
        assert cf.RERANKER_MODEL_DIR.startswith(cf.MODELS_DIR)
        assert cf.RAPIDOCR_MODEL_DIR.startswith(cf.MODELS_DIR)
        assert cf.PADDLEOCR_MODEL_DIR.startswith(cf.MODELS_DIR)
        assert cf.DENSE_MODEL_DIR.endswith(os.path.join("AI-ModelScope", "bge-base-zh-v1.5"))
        assert cf.RERANKER_MODEL_DIR.endswith(os.path.join("BAAI", "bge-reranker-base"))
        assert cf.RAPIDOCR_MODEL_DIR.endswith(os.path.join("RapidAI", "RapidOCR"))
        assert cf.PADDLEOCR_MODEL_DIR.endswith(os.path.join("PaddlePaddle", "PaddleOCR"))

    def test_ocr_uses_model_root_dir(self, monkeypatch):
        """RapidOCR constructs RapidOCR with Global.model_root_dir from config."""
        import config as cf
        from ocr.rapid import RapidOCR

        captured = {}

        class FakeRapidOCR:
            def __init__(self, **kwargs):
                captured["params"] = kwargs.get("params")

            def __call__(self, img):
                return None

        monkeypatch.setattr("rapidocr.RapidOCR", FakeRapidOCR)
        application = RapidOCR()
        application.start()

        assert captured["params"] == {
            "Global": {"model_root_dir": cf.RAPIDOCR_MODEL_DIR}
        }
        instance = application._ocr
        application.start()
        assert application._ocr is instance


# =============================================================================
# Rerank Tests
# =============================================================================
