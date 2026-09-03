import os
import sys
import json
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
import yaml
from fastapi.testclient import TestClient
from rag.auth import sign_request

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _test_database_url(value: str | None) -> str:
    if not value:
        return "postgresql://rag:rag@localhost:5432/rag_test"
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc, "/rag_test", parts.query, parts.fragment))


os.environ.setdefault("CONFIG_FILE", str(BACKEND_DIR / "config" / "qdrant-bgebase.yaml"))
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or _test_database_url(os.environ.get("DATABASE_URL"))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("OPENSEARCH_URL", "http://localhost:9200")
TEST_APP_ID = "myapp"
E2E_APP_ID = "myapp"


def _is_integration_item(item) -> bool:
    return item.get_closest_marker("integration") is not None or "/tests/integration/" in str(item.path)


@pytest.fixture(autouse=True)
def store_test_env(request, tmp_path):
    """Save and restore test runtime state."""
    if request.node.get_closest_marker("benchmark"):
        yield
        return

    import rag.config as cf
    orig_config_file_env = os.environ.get("CONFIG_FILE")
    orig_collection_prefix_env = os.environ.get("RAG_COLLECTION_PREFIX")
    orig_s3_bucket_env = os.environ.get("S3_BUCKET")
    orig_config = dict(cf.SEARCH_CONFIG)
    is_e2e = request.node.get_closest_marker("e2e") is not None
    touches_external_store = is_e2e or _is_integration_item(request.node)
    if is_e2e:
        os.environ["RAG_COLLECTION_PREFIX"] = os.environ.get("TEST_COLLECTION_PREFIX", "test")
        os.environ["S3_BUCKET"] = os.environ.get("TEST_S3_BUCKET", "rag-test")
    app_chunks_collection = f"{TEST_APP_ID}_chunks"
    if touches_external_store:
        _drop_qdrant_collection(cf.QDRANT_URL, app_chunks_collection)
    _reset_rate_limit()
    test_config_path = tmp_path / "app_test.yaml"
    raw_config = yaml.safe_load(_config_path(os.environ["CONFIG_FILE"]).read_text(encoding="utf-8"))
    raw_config["auth"]["registry_file"] = str(tmp_path / "apps.json")
    raw_config["api"]["rate_limit"] = "10000/minute"
    raw_config["api"]["rate_limit_index"] = "10000/minute"
    _isolate_index_backends(raw_config, tmp_path)
    test_config_path.write_text(yaml.safe_dump(raw_config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.environ["CONFIG_FILE"] = str(test_config_path)

    yield

    _reset_rate_limit()
    if touches_external_store:
        _drop_qdrant_collection(cf.QDRANT_URL, app_chunks_collection)
    cf.SEARCH_CONFIG.clear()
    cf.SEARCH_CONFIG.update(orig_config)
    if orig_config_file_env is None:
        os.environ.pop("CONFIG_FILE", None)
    else:
        os.environ["CONFIG_FILE"] = orig_config_file_env
    if orig_collection_prefix_env is None:
        os.environ.pop("RAG_COLLECTION_PREFIX", None)
    else:
        os.environ["RAG_COLLECTION_PREFIX"] = orig_collection_prefix_env
    if orig_s3_bucket_env is None:
        os.environ.pop("S3_BUCKET", None)
    else:
        os.environ["S3_BUCKET"] = orig_s3_bucket_env


@pytest.fixture
def chroma_test_env(store_test_env):
    """Compatibility fixture name for older tests during the Qdrant refactor."""
    return store_test_env


@pytest.fixture
def api_client(store_test_env):
    """FastAPI TestClient with the configured application."""
    import main
    from rag.api.runtime import runtime

    from rag.bootstrap import Application
    orig_application = runtime.application
    runtime.set_application(Application())
    orig_startup_in_background = runtime.startup_in_background
    runtime.startup_in_background = False

    try:
        with TestClient(main.app) as client:
            resp = client.post(
                "/api/open/rag/login",
                json={
                    "username": "admin",
                    "password": "admin123",
                },
            )
            assert resp.status_code == 200, resp.text
            client.headers.update({"Authorization": f"Bearer {resp.json()['access_token']}"})
            yield client
    finally:
        runtime.set_application(orig_application)
        runtime.startup_in_background = orig_startup_in_background


@pytest.fixture
def anonymous_api_client(store_test_env):
    """FastAPI TestClient without Authorization header."""
    import main
    from rag.api.runtime import runtime

    from rag.bootstrap import Application
    orig_application = runtime.application
    runtime.set_application(Application())
    orig_startup_in_background = runtime.startup_in_background
    runtime.startup_in_background = False

    try:
        with TestClient(main.app) as client:
            yield client
    finally:
        runtime.set_application(orig_application)
        runtime.startup_in_background = orig_startup_in_background


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
            "Authorization": "",
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
    _drop_runtime_app_data(E2E_APP_ID)
    app_resp = api_client.post("/api/open/rag/apps", json={"app_id": E2E_APP_ID})
    assert app_resp.status_code == 201, app_resp.text
    db_resp = api_client.post(f"/api/open/rag/apps/{E2E_APP_ID}/database")
    assert db_resp.status_code == 200, db_resp.text
    credential = app_resp.json()
    try:
        yield AppApiClient(api_client, E2E_APP_ID, credential["access_key"], credential["secret_key"])
    finally:
        _drop_runtime_app_data(E2E_APP_ID)


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
    from rag.parser.service import ParserService
    from rag.schema import ParserConfig

    parser = ParserService(ParserConfig())
    parser.start()
    try:
        chunks = parser.parse_file(test_txt_path)
    finally:
        parser.stop()
    initialized_store.add_file_chunks(chunks, file_id="testfile")
    return chunks


@pytest.fixture
def initialized_store(store_test_env):
    """Store module after explicit startup initialization."""
    from rag.scope import app_collection
    from dense.huggingface import HuggingFaceDense
    from rag.store.qdrant import QdrantStore

    dense = HuggingFaceDense()
    dense.start()
    store = QdrantStore(dense=dense)
    store.start()
    store.ensure_app_collection(TEST_APP_ID)
    with app_collection(TEST_APP_ID):
        yield store


class DeterministicReranker:
    """Deterministic reranker: scores (query, content) pairs by content length.

    Longer content gets a higher score. Replaces ``BAAI/bge-reranker-base``
    so tests never download or load the real CrossEncoder model.
    """

    def score(self, pairs):
        return [float(len(p[1])) for p in pairs]


class CrossEncoderLikeReranker:
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
    """Replace CrossEncoder loading in non-e2e tests."""
    if request.node.get_closest_marker("benchmark") or request.node.get_closest_marker("e2e"):
        yield
        return

    from rag.rerank.cross_encoder import CrossEncoderRerank

    monkeypatch.setattr(CrossEncoderRerank, "_load_reranker", lambda self: DeterministicReranker())
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


def _reset_rate_limit() -> None:
    try:
        from rag.api.rate_limit import reset_rate_limit

        reset_rate_limit()
    except Exception:
        pass


def _drop_runtime_app_data(app_id: str) -> None:
    try:
        from rag.api.runtime import runtime

        app = runtime.application
        app.store.drop_app_collection(app_id)
        sparse = getattr(app, "sparse", None)
        if sparse is not None and hasattr(sparse, "drop_app_collection"):
            sparse.drop_app_collection(app_id)
        app.database.purge_app(app_id)
        app.database.delete_app(app_id)
    except Exception:
        pass
    _drop_test_storage_data(app_id)


def _drop_test_storage_data(app_id: str) -> None:
    try:
        from rag.api.services.files import minio_client, storage_prefix

        bucket = os.environ.get("S3_BUCKET", "rag-test")
        client = minio_client()
        if not client.bucket_exists(bucket):
            return
        for item in client.list_objects(bucket, prefix=storage_prefix(app_id), recursive=True):
            client.remove_object(bucket, item.object_name)
    except Exception:
        pass


def _isolate_index_backends(raw_config: dict, tmp_path: Path) -> None:
    store = raw_config.get("store")
    if isinstance(store, dict):
        chroma = store.get("chroma")
        if isinstance(chroma, dict):
            chroma["persist_dir"] = str(tmp_path / "chroma_data")
        milvus_lite = store.get("milvus_lite")
        if isinstance(milvus_lite, dict):
            milvus_lite["uri"] = str(tmp_path / "milvus_lite.db")
    sparse = raw_config.get("sparse")
    if isinstance(sparse, dict):
        opensearch_bm25 = sparse.get("opensearch_bm25")
        if isinstance(opensearch_bm25, dict):
            opensearch_bm25["index_prefix"] = "test"
        elif (sparse.get("type") or sparse.get("name")) == "opensearch_bm25":
            sparse["index_prefix"] = "test"


def _config_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or path.exists():
        return path
    if path.parts and path.parts[0] == "rag":
        return BACKEND_DIR.parent / path
    return BACKEND_DIR / "config" / value


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
