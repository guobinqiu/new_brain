import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("CONFIG_FILE", str(BACKEND_DIR / "config" / "local.yaml"))


@pytest.fixture(autouse=True)
def store_test_env(request, tmp_path):
    """Save and restore Qdrant store module state for each test."""
    if request.node.get_closest_marker("benchmark"):
        yield
        return

    import store as st
    import config as cf

    orig_config_file_env = os.environ.get("CONFIG_FILE")
    orig_config = dict(cf.SEARCH_CONFIG)
    orig_common = cf.QDRANT_COMMON_COLLECTION
    orig_scoped = cf.QDRANT_SCOPED_COLLECTION
    orig_client = st._client
    orig_dense = st._dense
    orig_sparse = st._sparse
    orig_stores = dict(st._stores)
    orig_dense_vector_size = st._dense_vector_size
    orig_ready = st._ready
    import search as search_module
    orig_default_store = search_module._default_store

    st.close_store()
    search_module._default_store = None
    common_collection = "test_qdrant_knowledge_common"
    scoped_collection = "test_qdrant_knowledge_scoped"
    _drop_qdrant_collection(cf.QDRANT_URL, common_collection)
    _drop_qdrant_collection(cf.QDRANT_URL, scoped_collection)
    test_config_path = tmp_path / "qdrant_test.yaml"
    test_config_path.write_text(
        (BACKEND_DIR / "config" / "local.yaml")
        .read_text(encoding="utf-8")
        .replace("common: knowledge_common", f"common: {common_collection}")
        .replace("scoped: knowledge_scoped", f"scoped: {scoped_collection}"),
        encoding="utf-8",
    )
    os.environ["CONFIG_FILE"] = str(test_config_path)
    _set_qdrant_collection_names(cf, st, common_collection, scoped_collection)

    yield

    _drop_qdrant_collection(cf.QDRANT_URL, common_collection)
    _drop_qdrant_collection(cf.QDRANT_URL, scoped_collection)
    st.close_store()
    cf.SEARCH_CONFIG.clear()
    cf.SEARCH_CONFIG.update(orig_config)
    cf.QDRANT_COMMON_COLLECTION = orig_common
    cf.QDRANT_SCOPED_COLLECTION = orig_scoped
    _set_qdrant_collection_names(cf, st, orig_common, orig_scoped)
    st._client = orig_client
    st._dense = orig_dense
    st._sparse = orig_sparse
    st._stores.clear()
    st._stores.update(orig_stores)
    st._dense_vector_size = orig_dense_vector_size
    st._ready = orig_ready
    search_module._default_store = orig_default_store
    if orig_config_file_env is None:
        os.environ.pop("CONFIG_FILE", None)
    else:
        os.environ["CONFIG_FILE"] = orig_config_file_env


@pytest.fixture
def chroma_test_env(store_test_env):
    """Compatibility fixture name for older tests during the Qdrant refactor."""
    return store_test_env


@pytest.fixture
def api_client(store_test_env):
    """FastAPI TestClient with isolated store module state."""
    import main

    main.application = main.Application()
    orig_startup_in_background = main.STARTUP_IN_BACKGROUND
    main.STARTUP_IN_BACKGROUND = False

    try:
        with TestClient(main.app) as client:
            yield client
    finally:
        main.STARTUP_IN_BACKGROUND = orig_startup_in_background


@pytest.fixture
def test_txt_path(tmp_path):
    """Create a small .txt file that exercises both Chinese and English paths."""
    content = (
        "人工智能是计算机科学的一个重要分支。"
        "人工智能技术包括机器学习、深度学习和自然语言处理。"
        "AGI is the ultimate goal of AI research. "
        "Many companies are working on AGI. "
        "机器学习是人工智能的核心，而深度学习又是机器学习的一个重要子集。"
        "华为公司在人工智能领域投入了大量研发资源。"
        "华为的盘古大模型在自然语言处理方面表现出色。"
        "OpenAvatarChat is an open source project "
        "building intelligent dialogue systems using deep learning. "
    )
    path = tmp_path / "test_ai.txt"
    path.write_text(content, encoding="utf-8")
    return str(path)


@pytest.fixture
def uploaded_chunks(initialized_store, test_txt_path):
    """Parse *test_ai.txt* and add it to Qdrant common knowledge, returning chunks."""
    from document_parser import parse_file

    chunks = parse_file(test_txt_path)
    initialized_store.add_common_documents(chunks)
    return chunks


@pytest.fixture
def initialized_store(store_test_env):
    """Store module after explicit startup initialization."""
    import store
    from search import set_default_store

    store.init_search()
    set_default_store(store)
    return store


class FakeReranker:
    """Deterministic fake: scores (query, content) pairs by content length.

    Longer content gets a higher score. Replaces ``BAAI/bge-reranker-base``
    so tests never download or load the real CrossEncoder model.
    """

    def score(self, pairs):
        return [float(len(p[1])) for p in pairs]


class RealisticFakeReranker:
    """Mimics sentence-transformers 5.x CrossEncoder: has predict(), no score().

    sentence-transformers 5.6.1 renamed ``CrossEncoder.score()`` to
    ``CrossEncoder.predict()``. ``rerank.py`` must call ``predict`` on this
    API shape; calling ``score`` would raise AttributeError → 500.
    """

    def __init__(self):
        self.calls = []

    def predict(self, pairs):
        self.calls.append(pairs)
        # Longer content → higher score (deterministic)
        return [float(len(p[1])) for p in pairs]


@pytest.fixture(autouse=True)
def mock_reranker(request, monkeypatch):
    """Mock CrossEncoder loading so tests never download bge-reranker-base."""
    if request.node.get_closest_marker("benchmark"):
        yield
        return

    from rerank.cross_encoder import CrossEncoderRerank

    monkeypatch.setattr(CrossEncoderRerank, "_load_reranker", lambda self: FakeReranker())
    yield


@pytest.fixture
def test_img_path(tmp_path):
    """Create a PNG image with visible Chinese text for OCR testing."""
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 18)
    except OSError:
        font = ImageFont.load_default()

    img = Image.new("RGB", (600, 100), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 30), "人工智能AGI测试", fill="black", font=font)
    path = tmp_path / "test_ocr.png"
    img.save(path)
    return str(path)


def _set_qdrant_collection_names(config_module, store_module, common: str, scoped: str) -> None:
    config_module.QDRANT_COMMON_COLLECTION = common
    config_module.QDRANT_SCOPED_COLLECTION = scoped
    store_module.QDRANT_COMMON_COLLECTION = common
    store_module.QDRANT_SCOPED_COLLECTION = scoped
    store_module.COLLECTION_BY_TYPE = {
        "common": common,
        "scoped": scoped,
    }


def _drop_qdrant_collection(url: str, collection_name: str) -> None:
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=url)
        if client.collection_exists(collection_name):
            client.delete_collection(collection_name)
        close = getattr(client, "close", None)
        if callable(close):
            close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
