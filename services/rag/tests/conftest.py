import os
import sys
import uuid
from pathlib import Path

import pytest
import yaml

SERVICE_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


os.environ.setdefault("RAG_CONFIG_FILE", str(SERVICE_DIR / "tests" / "fixtures" / "qdrant-test.yaml"))


def _test_app_id_for_node(node) -> str:
    return f"test_{uuid.uuid4().hex}"


@pytest.fixture
def vector_test_env(request, tmp_path):
    """Save and restore test environment state."""
    import services.rag.core.config as cf
    orig_rag_config_file_env = os.environ.get("RAG_CONFIG_FILE")
    orig_config = dict(cf.SEARCH_CONFIG)
    raw_config = yaml.safe_load(_config_path(os.environ["RAG_CONFIG_FILE"]).read_text(encoding="utf-8"))
    _reset_rate_limit()
    test_config_path = tmp_path / "app_test.yaml"
    raw_config["api"]["rate_limit"] = "10000/minute"
    raw_config["api"]["rate_limit_index"] = "10000/minute"
    test_config_path.touch(mode=0o600)
    test_config_path.write_text(yaml.safe_dump(raw_config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.environ["RAG_CONFIG_FILE"] = str(test_config_path)

    yield

    _reset_rate_limit()
    cf.SEARCH_CONFIG.clear()
    cf.SEARCH_CONFIG.update(orig_config)
    if orig_rag_config_file_env is None:
        os.environ.pop("RAG_CONFIG_FILE", None)
    else:
        os.environ["RAG_CONFIG_FILE"] = orig_rag_config_file_env


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
def uploaded_chunks(initialized_vector, test_txt_path):
    """Add deterministic chunks without crossing into the parser service."""
    chunks = [
        {
            "id": "testfile-0",
            "content": "人工智能是计算机科学的一个重要分支。人工智能技术包括机器学习、深度学习和自然语言处理。",
            "metadata": {"filename": "test_ai.txt", "chunk_index": 0},
        },
        {
            "id": "testfile-1",
            "content": "AGI is the ultimate goal of AI research. Many companies are working on AGI.",
            "metadata": {"filename": "test_ai.txt", "chunk_index": 1},
        },
        {
            "id": "testfile-2",
            "content": "华为公司在人工智能领域投入了大量研发资源。华为的盘古大模型在自然语言处理方面表现出色。",
            "metadata": {"filename": "test_ai.txt", "chunk_index": 2},
        },
    ]
    initialized_vector.add_file_chunks(chunks, file_id="testfile")
    return chunks


@pytest.fixture
def initialized_vector(request, vector_test_env):
    """VectorClient module after explicit startup initialization."""
    from services.rag.core.loader import load_app_config

    config = load_app_config()
    yield from _initialized_vector_for_config(config, _test_app_id_for_node(request.node))


@pytest.fixture
def initialized_qdrant_vector(request, vector_test_env):
    from services.rag.core.loader import load_config_file

    config = load_config_file(PROJECT_ROOT / "services" / "rag" / "tests" / "fixtures" / "qdrant-test.yaml")
    yield from _initialized_vector_for_config(config, _test_app_id_for_node(request.node))


@pytest.fixture
def initialized_milvus_vector(request, vector_test_env):
    from services.rag.core.loader import load_config_file

    config = load_config_file(PROJECT_ROOT / "services" / "rag" / "tests" / "fixtures" / "milvus-test.yaml")
    yield from _initialized_vector_for_config(config, _test_app_id_for_node(request.node))


def _initialized_vector_for_config(config, app_id: str):
    from services.rag.core.scope import app_collection
    from services.rag.clients.vector.milvus import MilvusVectorClient
    from services.rag.clients.vector.qdrant import QdrantVectorClient

    vector_config = config.services.vector
    vector_key = vector_config.provider
    endpoint = vector_config.base_url
    if vector_key == "qdrant":
        _skip_if_qdrant_unavailable(endpoint)
    elif vector_key == "milvus":
        _skip_if_milvus_unavailable(endpoint)
    dense = DeterministicDense()
    dense.start()
    if vector_key == "qdrant":
        vector = QdrantVectorClient(
            dense=dense,
            url=endpoint,
            timeout=vector_config.timeout,
            query_timeout=vector_config.query_timeout,
            write_timeout=vector_config.write_timeout,
            init_timeout=vector_config.init_timeout,
            drop_timeout=vector_config.drop_timeout,
            quantization=vector_config.quantization,
            api_key=vector_config.api_key,
        )
    elif vector_key == "milvus":
        vector = MilvusVectorClient(
            dense=dense,
            uri=endpoint,
            timeout=vector_config.timeout,
            query_timeout=vector_config.query_timeout,
            write_timeout=vector_config.write_timeout,
            init_timeout=vector_config.init_timeout,
            drop_timeout=vector_config.drop_timeout,
            token=vector_config.token,
        )
    else:
        raise ValueError(f"unsupported vector: {vector_config.provider}")
    vector.start()
    vector.ensure_app_collection(app_id)
    try:
        with app_collection(app_id):
            yield vector
    finally:
        vector.stop()
        _drop_vector_collection(vector_key, app_id, endpoint=endpoint)


class DeterministicReranker:
    """Deterministic reranker: scores (query, content) pairs by content length.

    Longer content gets a higher score. Replaces ``BAAI/bge-reranker-base``
    so tests never download or load the real CrossEncoder model.
    """

    def score(self, pairs):
        return [float(len(p[1])) for p in pairs]


class DeterministicDense:
    vector_size = 4

    def __init__(self):
        self.ready = False

    def start(self):
        self.ready = True

    def stop(self):
        self.ready = False

    def embed_query(self, text):
        return self._embed(text)

    def embed_documents(self, texts):
        return [self._embed(text) for text in texts]

    def _embed(self, text):
        base = sum(ord(char) for char in text)
        return [
            float(base % 7),
            float(base % 11),
            float(base % 13),
            float(base % 17),
        ]


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


@pytest.fixture
def test_img_path(tmp_path):
    """Create a PNG image with visible Chinese text for image parsing tests."""
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 18)
    except OSError:
        font = ImageFont.load_default()

    img = Image.new("RGB", (600, 100), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 30), "人工智能AGI测试", fill="black", font=font)
    path = tmp_path / "test_image.png"
    img.save(path)
    return str(path)


def _drop_qdrant_collection(url: str, collection_name: str) -> None:
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=url, check_compatibility=False, api_key=os.getenv("QDRANT_API_KEY"))
        if client.collection_exists(collection_name):
            client.delete_collection(collection_name)
        close = getattr(client, "close", None)
        if callable(close):
            close()
    except Exception:
        pass


def _skip_if_qdrant_unavailable(url: str) -> None:
    if not _qdrant_available(url):
        pytest.skip(f"Qdrant is not available at {url}")


def _qdrant_available(url: str) -> bool:
    try:
        client = _make_qdrant_client(url)
        try:
            client.get_collections()
            return True
        finally:
            client.close()
    except Exception as exc:
        if _is_qdrant_connection_error(exc):
            return False
        raise


def _make_qdrant_client(url: str):
    from qdrant_client import QdrantClient

    return QdrantClient(url=url, timeout=2, api_key=os.getenv("QDRANT_API_KEY"))


def _is_qdrant_connection_error(exc: Exception) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    message = str(exc).lower()
    return any(marker in message for marker in (
        "connection refused",
        "failed to connect",
        "name or service not known",
        "nodename nor servname",
        "timed out",
        "timeout",
    ))


def _drop_milvus_collection(uri: str, collection_name: str) -> None:
    try:
        from services.rag.clients.vector.milvus import _connection_uri
        from pymilvus import MilvusClient

        client = MilvusClient(uri=_connection_uri(uri), token=os.getenv("MILVUS_TOKEN", ""))
        if client.has_collection(collection_name):
            client.drop_collection(collection_name)
        close = getattr(client, "close", None)
        if callable(close):
            close()
    except Exception:
        pass


def _skip_if_milvus_unavailable(uri: str) -> None:
    if not _milvus_available(uri):
        pytest.skip(f"Milvus is not available at {uri}")


def _milvus_available(uri: str) -> bool:
    try:
        client = _make_milvus_client(uri)
        client.list_collections(timeout=2)
        close = getattr(client, "close", None)
        if callable(close):
            close()
        return True
    except Exception as exc:
        if _is_milvus_connection_error(exc):
            return False
        raise


def _make_milvus_client(uri: str):
    from services.rag.clients.vector.milvus import _connection_uri
    from pymilvus import MilvusClient

    return MilvusClient(uri=_connection_uri(uri), timeout=2, token=os.getenv("MILVUS_TOKEN", ""))


def _is_milvus_connection_error(exc: Exception) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    message = str(exc).lower()
    return any(marker in message for marker in (
        "fail connecting",
        "failed to connect",
        "connection refused",
        "server unavailable",
        "deadline exceeded",
        "timed out",
        "timeout",
    ))


def _drop_vector_collection(vector_key: str, app_id: str, *, endpoint: str) -> None:
    collection_name = f"{app_id}_chunks"
    if vector_key == "qdrant":
        _drop_qdrant_collection(endpoint, collection_name)
    elif vector_key == "milvus":
        _drop_milvus_collection(endpoint, collection_name)


def _reset_rate_limit() -> None:
    try:
        from services.rag.core.api.rate_limit import reset_rate_limit

        reset_rate_limit()
    except Exception:
        pass


def _config_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or path.exists():
        return path
    if path.parts and path.parts[0] in {"rag", "services", "shared"}:
        return PROJECT_ROOT / path
    return SERVICE_DIR / "config" / value


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
