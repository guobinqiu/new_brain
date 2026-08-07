from __future__ import annotations

from pathlib import Path

from loader import load_app_config


CONFIG = load_app_config()

SEARCH_CONFIG = {
    "top_k": CONFIG.search.top_k,
    "fetch_k": CONFIG.search.fetch_k,
    "dense_weight": CONFIG.search.dense_weight,
    "sparse_weight": CONFIG.search.sparse_weight,
    "rrf_k": CONFIG.search.rrf_k,
}

QDRANT_URL = CONFIG.store.url or "http://localhost:6333"
QDRANT_COMMON_COLLECTION = CONFIG.store.collections.common
QDRANT_SCOPED_COLLECTION = CONFIG.store.collections.scoped

MODELS_DIR = str(Path(__file__).resolve().parent.parent / "models")

DENSE_MODEL_DIR = CONFIG.dense.model_path
RERANKER_MODEL_DIR = CONFIG.rerank.model_path
RAPIDOCR_MODEL_DIR = CONFIG.ocr.model_path
PADDLEOCR_MODEL_DIR = str(Path(__file__).resolve().parent.parent / "models" / "paddleocr")
