from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_load_app_config_loads_local_config(monkeypatch):
    from loader import load_app_config

    monkeypatch.delenv("CONFIG_FILE", raising=False)

    config = load_app_config()

    assert config.name == "local"
    assert config.store.type == "qdrant"
    assert config.store.url == "http://localhost:6333"
    assert config.store.collections.common == "knowledge_common"
    assert config.logging.level == "INFO"
    assert config.logging.file is None
    assert config.logging.max_bytes == 10485760
    assert config.logging.backup_count == 5
    assert config.logging.search_trace is True
    assert config.dense.import_path == "dense.huggingface.HuggingFaceDense"
    assert config.sparse.import_path == "sparse.bm25.BM25Sparse"
    assert config.store.import_path == "store.qdrant.QdrantStore"
    assert config.rerank.import_path == "rerank.cross_encoder.CrossEncoderRerank"
    assert config.ocr.import_path == "ocr.rapid.RapidOCR"


def test_load_app_config_can_use_explicit_yaml(monkeypatch, tmp_path):
    from loader import load_app_config

    path = tmp_path / "custom.yaml"
    path.write_text(
        """
dense: test_dense
sparse:
  type: bm25
  tokenizer: jieba
store:
  type: qdrant
  url: http://localhost:6333
  timeout: 42
  collections:
    common: common_custom
    scoped: scoped_custom
search:
  default_mode: hybrid
  top_k: 12
  fetch_k: 48
  dense_weight: 0.7
  sparse_weight: 0.3
  rrf_k: 80
logging:
  level: DEBUG
  file: logs/test-rag.jsonl
  max_bytes: 2048
  backup_count: 3
  search_trace: false
rerank: test_rerank
ocr: test_ocr
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_FILE", str(path))

    config = load_app_config()

    assert config.name == "custom"
    assert config.dense.model_path == str(PROJECT_ROOT / "models" / "dense")
    assert config.sparse.name == "bm25"
    assert config.sparse.tokenizer == "jieba"
    assert config.rerank.model_path == str(PROJECT_ROOT / "models" / "rerank")
    assert config.ocr.model_path == str(PROJECT_ROOT / "models" / "ocr")
    assert config.store.timeout == 42
    assert config.store.collections.common == "common_custom"
    assert config.search.top_k == 12
    assert config.search.fetch_k == 48
    assert config.search.dense_weight == 0.7
    assert config.logging.level == "DEBUG"
    assert config.logging.file == "logs/test-rag.jsonl"
    assert config.logging.max_bytes == 2048
    assert config.logging.backup_count == 3
    assert config.logging.search_trace is False


def test_load_app_config_selects_enabled_components_by_key(monkeypatch, tmp_path):
    from loader import load_app_config

    path = tmp_path / "key_config.yaml"
    path.write_text(
        """
dense:
  bge_base:
    enable: false
    model_name: bge-base-zh-v1.5
  bge_m3:
    enable: true
    model_name: bge-m3
sparse:
  bm25:
    enable: true
    tokenizer: jieba
store:
  qdrant:
    enable: true
    url: http://localhost:6333
    collections:
      common: common_custom
      scoped: scoped_custom
search:
  default_mode: hybrid
  top_k: 12
  fetch_k: 48
  dense_weight: 0.7
  sparse_weight: 0.3
  rrf_k: 80
rerank:
  bge_base:
    enable: true
    model_name: bge-reranker-base
ocr:
  rapid:
    enable: true
    model_name: rapidocr
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_FILE", str(path))

    config = load_app_config()

    assert config.dense.name == "bge_m3"
    assert config.dense.model_path == str(PROJECT_ROOT / "models" / "bge-m3")
    assert config.sparse.name == "bm25"
    assert config.sparse.tokenizer == "jieba"
    assert config.store.type == "qdrant"
    assert config.store.url == "http://localhost:6333"
    assert config.rerank.name == "bge_base"
    assert config.rerank.model_path == str(PROJECT_ROOT / "models" / "bge-reranker-base")


def test_load_app_config_can_use_config_filename(monkeypatch):
    from loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "local.yaml")

    config = load_app_config()

    assert config.name == "local"
    assert config.dense.model_path == str(PROJECT_ROOT / "models" / "bge-base-zh-v1.5")
    assert config.store.type == "qdrant"
    assert config.store.url == "http://localhost:6333"
    assert config.store.collections.common == "knowledge_common"


def test_load_app_config_supports_qdrant_profile(monkeypatch):
    from loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "qdrant.yaml")

    config = load_app_config()

    assert config.name == "qdrant"
    assert config.store.type == "qdrant"
    assert config.store.collections.common == "qdrant_knowledge_common"


def test_load_app_config_supports_chroma_store(monkeypatch):
    from loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "chroma.yaml")

    config = load_app_config()

    assert config.name == "chroma"
    assert config.store.type == "chroma"
    assert config.store.persist_dir == "chroma_data"
    assert config.store.collections.common == "chroma_knowledge_common"


def test_load_app_config_rejects_chroma_bge_m3_sparse(tmp_path):
    from loader import load_config_file

    path = tmp_path / "chroma_bge_m3_sparse.yaml"
    path.write_text(
        """
dense:
  bge_base:
    enable: true
    model_name: bge-base-zh-v1.5
    import_path: dense.huggingface.HuggingFaceDense
sparse:
  bge_m3:
    enable: true
    model_name: bge-m3
    import_path: sparse.qdrant_bge_m3.QdrantBGEM3Sparse
store:
  chroma:
    enable: true
    persist_dir: chroma_data
    collections:
      common: chroma_knowledge_common
      scoped: chroma_knowledge_scoped
    import_path: store.chroma.ChromaStore
search:
  default_mode: hybrid
rerank:
  bge_base:
    enable: true
    model_name: bge-reranker-base
    import_path: rerank.cross_encoder.CrossEncoderRerank
ocr:
  rapid:
    enable: true
    model_name: rapidocr
    import_path: ocr.rapid.RapidOCR
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Chroma 不支持 bge_m3 sparse"):
        load_config_file(path)


def test_load_app_config_supports_milvus_store(monkeypatch):
    from loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "milvus.yaml")

    config = load_app_config()
    raw = yaml.safe_load((PROJECT_ROOT / "backend" / "config" / "milvus.yaml").read_text(encoding="utf-8"))
    enabled_store = next(store for store in raw["store"].values() if store.get("enable") is True)

    assert config.name == "milvus"
    assert config.store.type == "milvus"
    assert config.store.uri == enabled_store["uri"]
    assert config.store.collections.common == enabled_store["collections"]["common"]


def test_load_app_config_keeps_bge_m3_sparse_model_path_independent(monkeypatch):
    from loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "local.yaml")

    config = load_app_config()

    assert config.dense.model_path == str(PROJECT_ROOT / "models" / "bge-base-zh-v1.5")
    assert config.sparse.name == "bm25"


def test_load_app_config_supports_milvus_builtin_bm25_sparse(monkeypatch):
    from loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "milvus.yaml")

    config = load_app_config()

    assert config.store.type == "milvus"
    assert config.sparse.name == "bm25"
    assert config.sparse.tokenizer == "jieba"


def test_load_app_config_supports_paddle_ocr(monkeypatch, tmp_path):
    from loader import load_app_config

    path = tmp_path / "paddle_ocr.yaml"
    path.write_text(
        """
dense:
  bge_base:
    enable: true
    model_name: bge-base-zh-v1.5
sparse:
  bm25:
    enable: true
    tokenizer: jieba
store:
  qdrant:
    enable: true
    url: http://localhost:6333
    collections:
      common: common
      scoped: scoped
search:
  default_mode: hybrid
rerank:
  bge_base:
    enable: true
    model_name: bge-reranker-base
ocr:
  paddle:
    enable: true
    model_name: paddleocr
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_FILE", str(path))

    config = load_app_config()

    assert config.ocr.name == "paddle"
    assert config.ocr.model_path == str(PROJECT_ROOT / "models" / "paddleocr")


def test_load_app_config_supports_tesseract_ocr(monkeypatch, tmp_path):
    from loader import load_app_config

    path = tmp_path / "tesseract_ocr.yaml"
    path.write_text(
        """
dense:
  bge_base:
    enable: true
    model_name: bge-base-zh-v1.5
sparse:
  bm25:
    enable: true
    tokenizer: jieba
store:
  qdrant:
    enable: true
    url: http://localhost:6333
    collections:
      common: common
      scoped: scoped
search:
  default_mode: hybrid
rerank:
  bge_base:
    enable: true
    model_name: bge-reranker-base
ocr:
  tesseract:
    enable: true
    model_name: tesseract
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_FILE", str(path))

    config = load_app_config()

    assert config.ocr.name == "tesseract"
    assert config.ocr.model_path == str(PROJECT_ROOT / "models" / "tesseract")


def test_load_app_config_rejects_unsupported_store(tmp_path):
    from loader import load_config_file

    path = tmp_path / "bad.yaml"
    path.write_text(
        """
dense: test_dense
sparse:
  type: bm25
  tokenizer: jieba
store:
  type: unknown
  collections:
    common: common
    scoped: scoped
search:
  default_mode: hybrid
rerank: test_rerank
ocr: test_ocr
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported store.type"):
        load_config_file(path)
