from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_load_app_config_defaults_to_default_yaml(monkeypatch):
    from loader import load_app_config

    monkeypatch.delenv("CONFIG_FILE", raising=False)

    config = load_app_config()

    assert config.name == "default"
    assert config.store.type == "store/qdrant"
    assert config.store.url == "http://localhost:6333"
    assert config.store.collections.common == "knowledge_common"


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
    assert config.store.collections.common == "common_custom"
    assert config.search.top_k == 12
    assert config.search.fetch_k == 48
    assert config.search.dense_weight == 0.7


def test_load_app_config_selects_enabled_components_by_module(monkeypatch, tmp_path):
    from loader import load_app_config

    path = tmp_path / "module_config.yaml"
    path.write_text(
        """
dense:
  base:
    enable: false
    module: dense/huggingface
    model_name: bge-base-zh-v1.5
  m3:
    enable: true
    module: dense/huggingface
    model_name: bge-m3
sparse:
  keywords:
    enable: true
    module: sparse/bm25
    tokenizer: jieba
store:
  local_qdrant:
    enable: true
    module: store/qdrant
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
  base:
    enable: true
    module: rerank/cross_encoder
    model_name: bge-reranker-base
ocr:
  rapid:
    enable: true
    module: ocr/rapid
    model_name: rapidocr
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_FILE", str(path))

    config = load_app_config()

    assert config.dense.name == "dense/huggingface"
    assert config.dense.model_path == str(PROJECT_ROOT / "models" / "bge-m3")
    assert config.sparse.name == "sparse/bm25"
    assert config.sparse.tokenizer == "jieba"
    assert config.store.type == "store/qdrant"
    assert config.store.url == "http://localhost:6333"
    assert config.rerank.name == "rerank/cross_encoder"
    assert config.rerank.model_path == str(PROJECT_ROOT / "models" / "bge-reranker-base")


def test_load_app_config_can_use_config_filename(monkeypatch):
    from loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "default.yaml")

    config = load_app_config()

    assert config.name == "default"
    assert config.dense.model_path == str(PROJECT_ROOT / "models" / "bge-base-zh-v1.5")
    assert config.store.type == "store/qdrant"
    assert config.store.url == "http://localhost:6333"
    assert config.store.collections.common == "knowledge_common"


def test_load_app_config_supports_qdrant_profile(monkeypatch):
    from loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "qdrant.yaml")

    config = load_app_config()

    assert config.name == "qdrant"
    assert config.store.type == "store/qdrant"
    assert config.store.collections.common == "qdrant_knowledge_common"


def test_load_app_config_supports_chroma_store(monkeypatch):
    from loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "chroma.yaml")

    config = load_app_config()

    assert config.name == "chroma"
    assert config.store.type == "store/chroma"
    assert config.store.persist_dir == "chroma_data"
    assert config.store.collections.common == "chroma_knowledge_common"


def test_load_app_config_supports_milvus_store(monkeypatch):
    from loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "milvus.yaml")

    config = load_app_config()
    raw = yaml.safe_load((PROJECT_ROOT / "backend" / "config" / "milvus.yaml").read_text(encoding="utf-8"))
    enabled_store = next(store for store in raw["store"].values() if store.get("enable") is True)

    assert config.name == "milvus"
    assert config.store.type == "store/milvus"
    assert config.store.uri == enabled_store["uri"]
    assert config.store.collections.common == enabled_store["collections"]["common"]


def test_load_app_config_keeps_bge_m3_sparse_model_path_independent(monkeypatch):
    from loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "default.yaml")

    config = load_app_config()

    assert config.dense.model_path == str(PROJECT_ROOT / "models" / "bge-base-zh-v1.5")
    assert config.sparse.name == "sparse/bm25"


def test_load_app_config_supports_milvus_builtin_bm25_sparse(monkeypatch):
    from loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "milvus.yaml")

    config = load_app_config()

    assert config.store.type == "store/milvus"
    assert config.sparse.name == "sparse/bm25"
    assert config.sparse.tokenizer == "jieba"


def test_load_app_config_supports_paddle_ocr(monkeypatch, tmp_path):
    from loader import load_app_config

    path = tmp_path / "paddle_ocr.yaml"
    path.write_text(
        """
dense:
  selected:
    enable: true
    module: dense/huggingface
    model_name: bge-base-zh-v1.5
sparse:
  selected:
    enable: true
    module: sparse/bm25
    tokenizer: jieba
store:
  selected:
    enable: true
    module: store/qdrant
    url: http://localhost:6333
    collections:
      common: common
      scoped: scoped
search:
  default_mode: hybrid
rerank:
  selected:
    enable: true
    module: rerank/cross_encoder
    model_name: bge-reranker-base
ocr:
  selected:
    enable: true
    module: ocr/paddle
    model_name: paddleocr
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_FILE", str(path))

    config = load_app_config()

    assert config.ocr.name == "ocr/paddle"
    assert config.ocr.model_path == str(PROJECT_ROOT / "models" / "paddleocr")


def test_load_app_config_supports_tesseract_ocr(monkeypatch, tmp_path):
    from loader import load_app_config

    path = tmp_path / "tesseract_ocr.yaml"
    path.write_text(
        """
dense:
  selected:
    enable: true
    module: dense/huggingface
    model_name: bge-base-zh-v1.5
sparse:
  selected:
    enable: true
    module: sparse/bm25
    tokenizer: jieba
store:
  selected:
    enable: true
    module: store/qdrant
    url: http://localhost:6333
    collections:
      common: common
      scoped: scoped
search:
  default_mode: hybrid
rerank:
  selected:
    enable: true
    module: rerank/cross_encoder
    model_name: bge-reranker-base
ocr:
  selected:
    enable: true
    module: ocr/tesseract
    model_name: tesseract
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_FILE", str(path))

    config = load_app_config()

    assert config.ocr.name == "ocr/tesseract"
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
