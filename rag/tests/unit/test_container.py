import pytest


pytestmark = pytest.mark.unit


def _config_file(tmp_path, store_key: str = "qdrant", sparse_key: str = "bm25", sparse_extra: str = "  tokenizer: jieba\n", ocr_key: str = "rapid", ocr_model_name: str = "rapidocr"):
    store_settings = {
        "qdrant": """
  url: http://localhost:6333
""",
        "chroma": """
  persist_dir: ./chroma_data
""",
        "milvus": """
  uri: http://localhost:19530
""",
    }[store_key]
    path = tmp_path / "profile.yaml"
    path.write_text(
        f"""
database:
  type: postgres
  url: postgresql://rag:rag@localhost:5432/rag
dense:
  name: bge_base
  model_name: bge-base-zh-v1.5
sparse:
  type: {sparse_key}
{sparse_extra.rstrip()}
store:
  type: {store_key}
{store_settings.rstrip()}
search:
  default_mode: hybrid
  top_k: 20
  fetch_k: 50
rerank:
  name: bge_base
  model_name: bge-reranker-base
ocr:
  name: {ocr_key}
  model_name: {ocr_model_name}
""",
        encoding="utf-8",
    )
    return path


def test_container_maps_sparse_config_to_injected_tokenizer(tmp_path):
    from rag.container import build_sparse, create_container
    from rag.loader import load_config_file
    from rag.sparse.bm25 import BM25Sparse

    config = load_config_file(_config_file(tmp_path))
    container = create_container(config)

    sparse = container.sparse()
    built_sparse = build_sparse(config)

    assert isinstance(sparse, BM25Sparse)
    assert isinstance(built_sparse, BM25Sparse)
    assert sparse.tokenizer.__class__.__name__ == "JiebaTokenizer"


def test_container_selects_chroma_store(tmp_path):
    from rag.container import create_container
    from rag.loader import load_config_file
    from store.chroma import ChromaStore

    config = load_config_file(_config_file(tmp_path, store_key="chroma"))
    container = create_container(config)

    store = container.store()

    assert isinstance(store, ChromaStore)
    assert store.persist_dir == config.store.persist_dir


def test_container_selects_milvus_store(tmp_path):
    from rag.container import create_container
    from rag.loader import load_config_file
    from store.milvus import MilvusStore

    config = load_config_file(_config_file(tmp_path, store_key="milvus"))
    container = create_container(config)

    store = container.store()

    assert isinstance(store, MilvusStore)
    assert store.uri == config.store.uri


def test_container_selects_qdrant_bge_m3_sparse_adapter(tmp_path):
    from rag.container import create_container
    from rag.loader import load_config_file
    from rag.sparse.qdrant_bge_m3 import QdrantBGEM3Sparse

    config = load_config_file(_config_file(tmp_path, sparse_key="bge_m3", sparse_extra="  model_name: bge-m3\n"))
    container = create_container(config)

    sparse = container.sparse()

    assert isinstance(sparse, QdrantBGEM3Sparse)


def test_container_selects_milvus_bge_m3_sparse_adapter(tmp_path):
    from rag.container import create_container
    from rag.loader import load_config_file
    from rag.sparse.milvus_bge_m3 import MilvusBGEM3Sparse

    config = load_config_file(_config_file(tmp_path, store_key="milvus", sparse_key="bge_m3", sparse_extra="  model_name: bge-m3\n"))
    container = create_container(config)

    sparse = container.sparse()

    assert isinstance(sparse, MilvusBGEM3Sparse)


def test_container_selects_milvus_builtin_bm25_sparse_adapter(tmp_path):
    from rag.container import create_container
    from rag.loader import load_config_file
    from rag.sparse.milvus_bm25 import MilvusBM25Sparse

    config = load_config_file(_config_file(tmp_path, store_key="milvus", sparse_key="milvus_bm25", sparse_extra=""))
    container = create_container(config)

    sparse = container.sparse()

    assert isinstance(sparse, MilvusBM25Sparse)


def test_container_selects_paddle_ocr_adapter(tmp_path):
    from rag.container import create_container
    from rag.loader import load_config_file
    from rag.ocr.paddle import PaddleOCR

    config = load_config_file(_config_file(tmp_path, ocr_key="paddle", ocr_model_name="paddleocr"))
    container = create_container(config)

    ocr = container.ocr()

    assert isinstance(ocr, PaddleOCR)
    assert ocr.model_dir == config.ocr.model_path


def test_container_selects_tesseract_ocr_adapter(tmp_path):
    from rag.container import create_container
    from rag.loader import load_config_file
    from rag.ocr.tesseract import TesseractOCR

    config = load_config_file(_config_file(tmp_path, ocr_key="tesseract", ocr_model_name="tesseract"))
    container = create_container(config)

    ocr = container.ocr()

    assert isinstance(ocr, TesseractOCR)


def test_container_builds_parser_component(tmp_path):
    from rag.container import create_container
    from rag.loader import load_config_file
    from rag.parser.service import ParserService

    config = load_config_file(_config_file(tmp_path))
    container = create_container(config)
    ocr = container.ocr()

    parser = container.parser(ocr=ocr)

    assert isinstance(parser, ParserService)
    assert parser.ocr is ocr
    assert parser.config is config.parser


def test_container_injects_store_into_search_pipeline(tmp_path):
    from rag.container import create_container
    from rag.loader import load_config_file

    config = load_config_file(_config_file(tmp_path))
    container = create_container(config)
    store = container.store()

    search = container.search(store=store)

    assert search.store is store


def test_container_maps_database_config_to_postgres(tmp_path):
    from rag.container import build_database, create_container
    from rag.database.postgres import PostgresDatabase
    from rag.loader import load_config_file

    config = load_config_file(_config_file(tmp_path))
    container = create_container(config)

    database = container.database()

    assert isinstance(database, PostgresDatabase)
    assert database.url == config.database.url
    assert database.pool_size == config.database.pool_size
    assert isinstance(build_database(config), PostgresDatabase)
