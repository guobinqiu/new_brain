import pytest

from schema import parse_app_config


pytestmark = pytest.mark.unit


def _base_raw(url=None):
    return {
        "database": {"type": "postgres", "url": url or "postgresql://rag:rag@localhost:5432/rag", "pool_size": 3},
        "dense": {"name": "test_dense", "model_path": "/tmp/dense"},
        "sparse": {"type": "bm25", "tokenizer": "jieba"},
        "store": {"type": "qdrant", "url": "http://localhost:6333"},
        "search": {},
        "rerank": None,
        "ocr": {"name": "test_ocr", "model_path": "/tmp/ocr"},
        "auth": {"admin": {"username": "admin", "password": "x"}},
    }


def test_database_config_parsed():
    config = parse_app_config(_base_raw())
    assert config.database.type == "postgres"
    assert config.database.url == "postgresql://rag:rag@localhost:5432/rag"
    assert config.database.pool_size == 3


def test_database_url_required():
    raw = _base_raw()
    raw["database"] = {"type": "postgres"}
    with pytest.raises(ValueError):
        parse_app_config(raw)


def test_database_type_whitelisted():
    raw = _base_raw()
    raw["database"] = {"type": "mysql", "url": "mysql://x"}
    with pytest.raises(ValueError):
        parse_app_config(raw)
