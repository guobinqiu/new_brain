import pytest


pytestmark = pytest.mark.unit


def test_enabled_store_key_reads_enabled_store_group():
    from rag.tests import conftest

    assert conftest._enabled_store_key({"store": {"qdrant": {"enable": True}, "milvus": {"enable": False}}}) == "qdrant"
    assert conftest._enabled_store_key({"store": {"qdrant": {"enable": False}, "milvus": {"enable": True}}}) == "milvus"
    assert conftest._enabled_store_key({"store": {"type": "milvus"}}) == "milvus"


def test_drop_store_collection_uses_configured_store(monkeypatch):
    from rag.tests import conftest

    calls = []

    monkeypatch.setattr(conftest, "_drop_qdrant_collection", lambda url, name: calls.append(("qdrant", url, name)))
    monkeypatch.setattr(conftest, "_drop_milvus_collection", lambda uri, name: calls.append(("milvus", uri, name)))

    conftest._drop_store_collection(
        {"store": {"qdrant": {"enable": False}, "milvus": {"enable": True}}},
        "myapp",
        qdrant_url="http://qdrant:6333",
        milvus_uri="http://milvus:19530",
    )

    assert calls == [("milvus", "http://milvus:19530", "myapp_chunks")]


def test_drop_store_collection_uses_milvus_lite_branch(monkeypatch):
    from rag.tests import conftest

    calls = []

    monkeypatch.setattr(conftest, "_drop_qdrant_collection", lambda url, name: calls.append(("qdrant", url, name)))
    monkeypatch.setattr(conftest, "_drop_milvus_collection", lambda uri, name: calls.append(("milvus", uri, name)))

    conftest._drop_store_collection(
        {"store": {"milvus_lite": {"enable": True}}},
        "myapp",
        qdrant_url="http://qdrant:6333",
        milvus_uri="milvus_data/lite/test.db",
    )

    assert calls == [("milvus", "milvus_data/lite/test.db", "myapp_chunks")]


def test_milvus_skip_helper_skips_when_connection_fails(monkeypatch):
    from rag.tests import conftest

    monkeypatch.setattr(conftest, "_milvus_available", lambda uri: False)

    with pytest.raises(pytest.skip.Exception):
        conftest._skip_if_milvus_unavailable("http://milvus:19530")


def test_qdrant_skip_helper_skips_when_connection_fails(monkeypatch):
    from rag.tests import conftest

    monkeypatch.setattr(conftest, "_qdrant_available", lambda url: False)

    with pytest.raises(pytest.skip.Exception):
        conftest._skip_if_qdrant_unavailable("http://qdrant:6333")


def test_milvus_available_does_not_hide_non_connection_errors(monkeypatch):
    from rag.tests import conftest

    def raise_non_connection_error(uri):
        raise RuntimeError("authentication failed")

    monkeypatch.setattr(conftest, "_make_milvus_client", raise_non_connection_error)

    with pytest.raises(RuntimeError, match="authentication failed"):
        conftest._milvus_available("http://milvus:19530")
