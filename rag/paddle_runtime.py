from __future__ import annotations

import os

from rag.config import PADDLEOCR_MODEL_DIR


def prepare_paddle_runtime() -> None:
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", PADDLEOCR_MODEL_DIR)
