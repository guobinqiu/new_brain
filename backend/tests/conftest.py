import os
import sys
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from auth import sign_request

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("CONFIG_FILE", str(BACKEND_DIR / "config" / "local.yaml"))
TEST_APP_ID = "test_imsdom"


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
    app_chunks_collection = f"{TEST_APP_ID}_chunks"
    _drop_qdrant_collection(cf.QDRANT_URL, app_chunks_collection)
    test_config_path = tmp_path / "qdrant_test.yaml"
    test_config_path.write_text(
        (BACKEND_DIR / "config" / "local.yaml")
        .read_text(encoding="utf-8")
        .replace("auth:\n  admin:", f"auth:\n  registry_file: {tmp_path / 'apps.json'}\n  admin:"),
        encoding="utf-8",
    )
    os.environ["CONFIG_FILE"] = str(test_config_path)

    yield

    _drop_qdrant_collection(cf.QDRANT_URL, app_chunks_collection)
    st.close_store()
    cf.SEARCH_CONFIG.clear()
    cf.SEARCH_CONFIG.update(orig_config)
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

    from database.base import FakeDatabase
    main.application = main.Application(database=FakeDatabase())
    orig_startup_in_background = main.STARTUP_IN_BACKGROUND
    main.STARTUP_IN_BACKGROUND = False

    try:
        with TestClient(main.app) as client:
            resp = client.post(
                "/api/login",
                json={
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


class AppApiClient:
    def __init__(self, client, app_id: str, access_key: str, secret_key: str):
        self._client = client
        self.app_id = app_id
        self.access_key = access_key
        self.secret_key = secret_key

    def post(self, path: str, *, json=None, **kwargs):
        if json is None:
            body = b""
        else:
            body = json_dumps(json).encode("utf-8")
        timestamp = str(int(time.time()))
        headers = {
            "content-type": "application/json",
            "x-app-id": self.app_id,
            "x-access-key": self.access_key,
            "x-timestamp": timestamp,
            "x-signature": sign_request(self.secret_key, "POST", path, timestamp, body, self.app_id),
        }
        headers.update(kwargs.pop("headers", {}))
        return self._client.post(path, content=body, headers=headers, **kwargs)


@pytest.fixture
def app_api_client(api_client):
    app_resp = api_client.post("/api/apps", json={"app_id": TEST_APP_ID})
    assert app_resp.status_code == 201, app_resp.text
    db_resp = api_client.post(f"/api/apps/{TEST_APP_ID}/database")
    assert db_resp.status_code == 200, db_resp.text
    credential = app_resp.json()
    return AppApiClient(api_client, TEST_APP_ID, credential["access_key"], credential["secret_key"])


def json_dumps(value) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


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


def _drop_qdrant_collection(url: str, collection_name: str) -> None:
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=url, check_compatibility=False)
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
