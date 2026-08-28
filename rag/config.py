from __future__ import annotations

from pathlib import Path

from rag.loader import load_app_config


CONFIG = load_app_config()

SEARCH_CONFIG = {
    "default_mode": CONFIG.search.default_mode,
    "top_k": CONFIG.search.top_k,
    "rerank": CONFIG.rerank is not None,
    "rerank_available": CONFIG.rerank is not None,
    "fetch_k": CONFIG.search.fetch_k,
    "dense_weight": CONFIG.search.dense_weight,
    "sparse_weight": CONFIG.search.sparse_weight,
    "rrf_k": CONFIG.search.rrf_k,
}

QDRANT_URL = CONFIG.store.url or "http://localhost:6333"
MODELS_DIR = str(Path(__file__).resolve().parent.parent / "models")

DENSE_MODEL_DIR = CONFIG.dense.model_path
RERANKER_MODEL_DIR = CONFIG.rerank.model_path if CONFIG.rerank is not None else str(Path(__file__).resolve().parent.parent / "models" / "BAAI" / "bge-reranker-base")
RAPIDOCR_MODEL_DIR = str(Path(__file__).resolve().parent.parent / "models" / "RapidAI" / "RapidOCR")
PADDLEOCR_MODEL_DIR = str(Path(__file__).resolve().parent.parent / "models" / "PaddlePaddle" / "PaddleOCR")
