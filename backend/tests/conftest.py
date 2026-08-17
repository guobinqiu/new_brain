import hashlib
import hmac
import json
import os
import re
import sys
import time
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
    orig_chunks = cf.QDRANT_CHUNKS_COLLECTION
    orig_client = st._client
    orig_dense = st._dense
    orig_sparse = st._sparse
    stores = getattr(st, "_stores", None)
    orig_stores = dict(stores) if stores is not None else None
    orig_dense_vector_size = st._dense_vector_size
    orig_ready = st._ready
    import search as search_module
    orig_default_store = search_module._default_store

    st.close_store()
    search_module._default_store = None
    chunks_collection = f"test_qdrant_{_collection_suffix(request.node.nodeid)}"
    _drop_qdrant_collection(cf.QDRANT_URL, chunks_collection)
    test_config_path = tmp_path / "qdrant_test.yaml"
    test_config_path.write_text(
        (BACKEND_DIR / "config" / "local.yaml")
        .read_text(encoding="utf-8")
        .replace("chunks: knowledge_chunks", f"chunks: {chunks_collection}"),
        encoding="utf-8",
    )
    os.environ["CONFIG_FILE"] = str(test_config_path)
    _set_qdrant_collection_name(cf, st, chunks_collection)

    yield

    _drop_qdrant_collection(cf.QDRANT_URL, chunks_collection)
    st.close_store()
    cf.SEARCH_CONFIG.clear()
    cf.SEARCH_CONFIG.update(orig_config)
    cf.QDRANT_CHUNKS_COLLECTION = orig_chunks
    _set_qdrant_collection_name(cf, st, orig_chunks)
    st._client = orig_client
    st._dense = orig_dense
    st._sparse = orig_sparse
    stores = getattr(st, "_stores", None)
    if stores is not None and orig_stores is not None:
        stores.clear()
        stores.update(orig_stores)
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
            resp = client.post(
                "/api/auth/token",
                json={
                    "grant_type": "password",
                    "username": "admin",
                    "password": "admin123",
                },
            )
            assert resp.status_code == 200, resp.text
            client.headers.update({"Authorization": f"Bearer {resp.json()['access_token']}"})
            yield client
    finally:
        main.STARTUP_IN_BACKGROUND = orig_startup_in_background


@pytest.fixture
def anonymous_api_client(store_test_env):
    """FastAPI TestClient without Authorization header."""
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
def app_api_client(api_client):
    body = json.dumps({"grant_type": "client_credentials"}, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    app_id = "imsdom"
    secret_key = "78ddbd0730125b050b607c81c8398c4fe96f707cfa66f222d42a8eeae3aa47e6"
    body_sha256 = hashlib.sha256(body).hexdigest()
    string_to_sign = "\n".join(["POST", "/api/auth/token", timestamp, body_sha256, app_id])
    signature = hmac.new(secret_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    resp = api_client.post(
        "/api/auth/token",
        content=body,
        headers={
            "content-type": "application/json",
            "x-app-id": app_id,
            "x-access-key": "0d01c6bc9577a6dae3095cb7972a9f8c",
            "x-timestamp": timestamp,
            "x-signature": signature,
        },
    )
    assert resp.status_code == 200, resp.text
    api_client.headers.update({"Authorization": f"Bearer {resp.json()['access_token']}"})
    return api_client


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
    initialized_store.add_file_chunks(chunks, file_id="testfile")
    return chunks


@pytest.fixture
def initialized_store(store_test_env):
    """Store module after explicit startup initialization."""
    import store
    from dense.huggingface import HuggingFaceDense
    from search import set_default_store

    dense = HuggingFaceDense()
    dense.start()
    store.init_store(dense=dense)
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


def _set_qdrant_collection_name(config_module, store_module, collection_name: str) -> None:
    config_module.QDRANT_CHUNKS_COLLECTION = collection_name
    store_module.QDRANT_CHUNKS_COLLECTION = collection_name
    store_module.COLLECTION_BY_TYPE = {
        "common": collection_name,
        "scoped": collection_name,
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


def _collection_suffix(nodeid: str) -> str:
    suffix = re.sub(r"[^a-zA-Z0-9_]+", "_", nodeid).strip("_").lower()
    return suffix[-48:] or "knowledge_chunks"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
