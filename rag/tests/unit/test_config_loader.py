from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_load_app_config_loads_local_config(monkeypatch):
    from rag.loader import load_app_config

    monkeypatch.delenv("CONFIG_FILE", raising=False)

    config = load_app_config()

    assert config.name == "local"
    assert config.store.type == "qdrant"
    assert config.store.url == "http://localhost:6333"
    assert config.logging.level == "INFO"
    assert config.logging.file == "logs/rag.log"
    assert config.logging.max_bytes == 10485760
    assert config.logging.backup_count == 5
    assert config.logging.search_trace is True
    assert config.dense.import_path == "dense.huggingface.HuggingFaceDense"
    assert config.sparse.import_path == "sparse.bm25.BM25Sparse"
    assert config.store.import_path == "store.qdrant.QdrantStore"
    assert config.api.rate_limit == "120/minute"
    assert config.api.rate_limit_index == "10/minute"
    assert config.rerank is None
    assert config.ocr.import_path == "ocr.paddle.PaddleOCR"


def test_load_app_config_can_use_explicit_yaml(monkeypatch, tmp_path):
    from rag.loader import load_app_config

    path = tmp_path / "custom.yaml"
    path.write_text(
        """
database:
  type: postgres
  url: postgresql://rag:rag@localhost:5432/rag
dense: test_dense
sparse:
  type: bm25
  tokenizer: jieba
store:
  type: qdrant
  url: http://localhost:6333
  timeout: 42
search:
  default_mode: hybrid
  top_k: 12
  fetch_k: 48
  dense_weight: 0.7
  sparse_weight: 0.3
  rrf_k: 80
parser:
  mineru:
    enable: true
    text:
      chunk_size: 321
      chunk_overlap: 45
  unstructured:
    enable: false
logging:
  level: DEBUG
  file: logs/test-rag.jsonl
  max_bytes: 2048
  backup_count: 3
  search_trace: false
api:
  rate_limit: 60/minute
  rate_limit_index: 5/minute
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
    assert config.search.top_k == 12
    assert config.search.fetch_k == 48
    assert config.search.dense_weight == 0.7
    assert config.parser.mineru.text.chunk_size == 321
    assert config.parser.mineru.text.chunk_overlap == 45
    assert config.logging.level == "DEBUG"
    assert config.logging.file == "logs/test-rag.jsonl"
    assert config.logging.max_bytes == 2048
    assert config.logging.backup_count == 3
    assert config.logging.search_trace is False
    assert config.api.rate_limit == "60/minute"
    assert config.api.rate_limit_index == "5/minute"


def test_load_app_config_supports_embedding_runtime_config(monkeypatch, tmp_path):
    from rag.loader import load_app_config

    path = tmp_path / "embedding_config.yaml"
    path.write_text(
        """
database:
  type: postgres
  url: postgresql://rag:rag@localhost:5432/rag
dense: bge_m3
sparse:
  type: bge_m3
  model_name: bge-m3
store:
  type: qdrant
  url: http://localhost:6333
embedding:
  dense_batch_size: 32
  sparse_batch_size: 16
  release_memory: after_call
rerank: test_rerank
ocr: test_ocr
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_FILE", str(path))

    config = load_app_config()

    assert config.embedding.dense_batch_size == 32
    assert config.embedding.sparse_batch_size == 16
    assert config.embedding.release_memory == "after_call"


def test_load_app_config_rejects_multiple_enabled_parsers(monkeypatch, tmp_path):
    from rag.loader import load_app_config

    path = tmp_path / "multiple_parsers.yaml"
    path.write_text(
        """
database:
  type: postgres
  url: postgresql://rag:rag@localhost:5432/rag
dense: test_dense
sparse:
  type: bm25
  tokenizer: jieba
store:
  type: qdrant
  url: http://localhost:6333
parser:
  mineru:
    enable: true
  unstructured:
    enable: true
rerank: test_rerank
ocr: test_ocr
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_FILE", str(path))

    with pytest.raises(ValueError, match="parser must enable exactly one backend"):
        load_app_config()


def test_load_app_config_supports_unstructured_parser(monkeypatch, tmp_path):
    from rag.loader import load_app_config

    path = tmp_path / "unstructured_parser.yaml"
    path.write_text(
        """
database:
  type: postgres
  url: postgresql://rag:rag@localhost:5432/rag
dense: test_dense
sparse:
  type: bm25
  tokenizer: jieba
store:
  type: qdrant
  url: http://localhost:6333
parser:
  mineru:
    enable: false
  unstructured:
    enable: true
rerank: test_rerank
ocr: test_ocr
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_FILE", str(path))

    config = load_app_config()

    assert config.parser.enabled_parser == "unstructured"
    assert config.parser.unstructured.strategy == "hi_res"
    assert config.parser.unstructured.infer_table_structure is True
    assert config.parser.unstructured.languages == ["chi_sim", "eng"]


def test_load_app_config_supports_nested_parser_config(monkeypatch, tmp_path):
    from rag.loader import load_app_config

    path = tmp_path / "nested_parser.yaml"
    path.write_text(
        """
database:
  type: postgres
  url: postgresql://rag:rag@localhost:5432/rag
dense: test_dense
sparse:
  type: bm25
  tokenizer: jieba
store:
  type: qdrant
  url: http://localhost:6333
parser:
  mineru:
    enable: true
    text:
      chunk_size: 321
      chunk_overlap: 45
    table:
      header_backward_chars: 120
      footer_forward_chars: 80
  unstructured:
    enable: false
    languages:
      - eng
    text:
      chunk_size: 654
      chunk_overlap: 32
    table:
      header_backward_chars: 60
      footer_forward_chars: 40
rerank: test_rerank
ocr: test_ocr
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_FILE", str(path))

    config = load_app_config()

    assert config.parser.enabled_parser == "mineru"
    assert config.parser.unstructured.strategy == "hi_res"
    assert config.parser.unstructured.infer_table_structure is True
    assert config.parser.unstructured.languages == ["eng"]
    assert config.parser.mineru.text.chunk_size == 321
    assert config.parser.mineru.text.chunk_overlap == 45
    assert config.parser.mineru.table.header_backward_chars == 120
    assert config.parser.mineru.table.footer_forward_chars == 80
    assert config.parser.unstructured.text.chunk_size == 654
    assert config.parser.unstructured.text.chunk_overlap == 32


def test_load_app_config_supports_single_vector_sparse(monkeypatch, tmp_path):
    from rag.loader import load_app_config

    path = tmp_path / "single_vector_sparse.yaml"
    path.write_text(
        """
database:
  type: postgres
  url: postgresql://rag:rag@localhost:5432/rag
dense: bge_m3
sparse:
  type: bge_m3
  model_name: bge-m3
store:
  type: qdrant
  url: http://localhost:6333
search:
  default_mode: hybrid
rerank: test_rerank
ocr: test_ocr
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_FILE", str(path))

    config = load_app_config()

    assert config.sparse.name == "bge_m3"
    assert config.sparse.model_path == str(PROJECT_ROOT / "models" / "BAAI" / "bge-m3")


def test_load_app_config_rejects_nested_sparse_backends(monkeypatch, tmp_path):
    from rag.loader import load_app_config

    path = tmp_path / "nested_sparse.yaml"
    path.write_text(
        """
database:
  type: postgres
  url: postgresql://rag:rag@localhost:5432/rag
dense: bge_m3
sparse:
  app:
    type: bm25
  vector:
    type: bge_m3
store:
  type: qdrant
  url: http://localhost:6333
search:
  default_mode: hybrid
rerank: test_rerank
ocr: test_ocr
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_FILE", str(path))

    with pytest.raises(ValueError, match="sparse must define exactly one backend"):
        load_app_config()


def test_load_app_config_selects_named_components(monkeypatch, tmp_path):
    from rag.loader import load_app_config

    path = tmp_path / "key_config.yaml"
    path.write_text(
        """
database:
  type: postgres
  url: postgresql://rag:rag@localhost:5432/rag
dense:
  name: bge_m3
  model_name: bge-m3
sparse:
  type: bm25
  tokenizer: jieba
store:
  type: qdrant
  url: http://localhost:6333
search:
  default_mode: hybrid
  top_k: 12
  fetch_k: 48
  dense_weight: 0.7
  sparse_weight: 0.3
  rrf_k: 80
rerank:
  name: bge_base
  model_name: bge-reranker-base
ocr:
  name: rapid
  model_name: rapidocr
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_FILE", str(path))

    config = load_app_config()

    assert config.dense.name == "bge_m3"
    assert config.dense.model_path == str(PROJECT_ROOT / "models" / "BAAI" / "bge-m3")
    assert config.sparse.name == "bm25"
    assert config.sparse.tokenizer == "jieba"
    assert config.store.type == "qdrant"
    assert config.store.url == "http://localhost:6333"
    assert config.rerank.name == "bge_base"
    assert config.rerank.model_path == str(PROJECT_ROOT / "models" / "BAAI" / "bge-reranker-base")


def test_load_app_config_allows_profile_without_rerank(monkeypatch, tmp_path):
    from rag.loader import load_app_config

    path = tmp_path / "no_rerank.yaml"
    path.write_text(
        """
database:
  type: postgres
  url: postgresql://rag:rag@localhost:5432/rag
dense:
  name: bge_base
  model_name: bge-base-zh-v1.5
sparse:
  type: bm25
  tokenizer: jieba
store:
  type: qdrant
  url: http://localhost:6333
rerank: null
ocr:
  name: rapid
  model_name: rapidocr
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_FILE", str(path))

    config = load_app_config()

    assert config.rerank is None


def test_load_app_config_can_use_config_filename(monkeypatch):
    from rag.loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "local.yaml")

    config = load_app_config()

    assert config.name == "local"
    assert config.dense.model_path == str(PROJECT_ROOT / "models" / "AI-ModelScope" / "bge-base-zh-v1.5")
    assert config.store.type == "qdrant"
    assert config.store.url == "http://localhost:6333"


def test_load_app_config_applies_runtime_url_overrides(monkeypatch):
    from rag.loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "docker-cpu.yaml")
    monkeypatch.setenv("DATABASE_URL", "postgresql://rag:rag@19.16.1.233:5432/rag")
    monkeypatch.setenv("QDRANT_URL", "http://19.16.1.233:6333")

    config = load_app_config()

    assert config.database.url == "postgresql://rag:rag@19.16.1.233:5432/rag"
    assert config.store.url == "http://19.16.1.233:6333"


def test_load_app_config_supports_qdrant_profile(monkeypatch):
    from rag.loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "qdrant-bge-base.yaml")

    config = load_app_config()

    assert config.name == "qdrant-bge-base"
    assert config.store.type == "qdrant"


def test_load_app_config_supports_chroma_store(monkeypatch):
    from rag.loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "chroma-bge-base.yaml")

    config = load_app_config()

    assert config.name == "chroma-bge-base"
    assert config.store.type == "chroma"
    assert config.store.persist_dir == "chroma_data"


def test_load_app_config_rejects_chroma_bge_m3_sparse(tmp_path):
    from rag.loader import load_config_file

    path = tmp_path / "chroma_bge_m3_sparse.yaml"
    path.write_text(
        """
database:
  type: postgres
  url: postgresql://rag:rag@localhost:5432/rag
dense:
  name: bge_base
  model_name: bge-base-zh-v1.5
  import_path: dense.huggingface.HuggingFaceDense
sparse:
  type: bge_m3
  model_name: bge-m3
  import_path: sparse.qdrant_bge_m3.QdrantBGEM3Sparse
store:
  type: chroma
  persist_dir: chroma_data
  import_path: store.chroma.ChromaStore
search:
  default_mode: hybrid
rerank:
  name: bge_base
  model_name: bge-reranker-base
  import_path: rerank.cross_encoder.CrossEncoderRerank
ocr:
  name: rapid
  model_name: rapidocr
  import_path: ocr.rapid.RapidOCR
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Chroma 不支持 bge_m3 sparse"):
        load_config_file(path)


def test_load_app_config_supports_milvus_store(monkeypatch):
    from rag.loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "milvus-bge-base.yaml")

    config = load_app_config()

    assert config.name == "milvus-bge-base"
    assert config.store.type == "milvus"
    assert config.store.uri == "http://localhost:19530"


def test_load_app_config_keeps_app_bm25_sparse_without_model_path(monkeypatch):
    from rag.loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "local.yaml")

    config = load_app_config()

    assert config.dense.model_path == str(PROJECT_ROOT / "models" / "AI-ModelScope" / "bge-base-zh-v1.5")
    assert config.sparse.name == "bm25"


def test_load_app_config_supports_milvus_builtin_bm25_sparse(monkeypatch):
    from rag.loader import load_app_config

    monkeypatch.setenv("CONFIG_FILE", "milvus-builtin-bm25.yaml")

    config = load_app_config()

    assert config.store.type == "milvus"
    assert config.sparse.name == "milvus_bm25"
    assert config.sparse.tokenizer == "jieba"


def test_load_app_config_supports_paddle_ocr(monkeypatch, tmp_path):
    from rag.loader import load_app_config

    path = tmp_path / "paddle_ocr.yaml"
    path.write_text(
        """
database:
  type: postgres
  url: postgresql://rag:rag@localhost:5432/rag
dense:
  name: bge_base
  model_name: bge-base-zh-v1.5
sparse:
  type: bm25
  tokenizer: jieba
store:
  type: qdrant
  url: http://localhost:6333
search:
  default_mode: hybrid
rerank:
  name: bge_base
  model_name: bge-reranker-base
ocr:
  name: paddle
  model_name: paddleocr
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_FILE", str(path))

    config = load_app_config()

    assert config.ocr.name == "paddle"
    assert config.ocr.model_path == str(PROJECT_ROOT / "models" / "PaddlePaddle" / "PaddleOCR")


def test_load_app_config_supports_tesseract_ocr(monkeypatch, tmp_path):
    from rag.loader import load_app_config

    path = tmp_path / "tesseract_ocr.yaml"
    path.write_text(
        """
database:
  type: postgres
  url: postgresql://rag:rag@localhost:5432/rag
dense:
  name: bge_base
  model_name: bge-base-zh-v1.5
sparse:
  type: bm25
  tokenizer: jieba
store:
  type: qdrant
  url: http://localhost:6333
search:
  default_mode: hybrid
rerank:
  name: bge_base
  model_name: bge-reranker-base
ocr:
  name: tesseract
  model_name: tesseract
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_FILE", str(path))

    config = load_app_config()

    assert config.ocr.name == "tesseract"
    assert config.ocr.model_path == str(PROJECT_ROOT / "models" / "tesseract")


def test_load_app_config_rejects_unsupported_store(tmp_path):
    from rag.loader import load_config_file

    path = tmp_path / "bad.yaml"
    path.write_text(
        """
database:
  type: postgres
  url: postgresql://rag:rag@localhost:5432/rag
dense: test_dense
sparse:
  type: bm25
  tokenizer: jieba
store:
  type: unknown
search:
  default_mode: hybrid
rerank: test_rerank
ocr: test_ocr
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported store.type"):
        load_config_file(path)
