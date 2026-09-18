import pytest
from fastapi import FastAPI

from shared.config import parse_app_config
from services.rag.clients.inference import HttpInferenceClient
from services.rag.clients.parser import HttpParserClient
from services.rag.clients.vector.qdrant import QdrantVectorClient


pytestmark = pytest.mark.unit


def test_required_component_status_has_no_disabled_state(monkeypatch):
    from services.rag.core.api.services import common as service

    class StoppedComponent:
        ready = False

    assert service.required_component_status(StoppedComponent()) == "error"
    assert service.required_component_status(StoppedComponent(), error="failed") == "error"


@pytest.mark.parametrize("has_database", [True, False])
def test_lifespan_wires_clients(monkeypatch, has_database):
    import asyncio
    from shared.config import LoggingConfig

    class VectorClient:
        def __init__(self):
            self.initialized = []

        def ensure_app_collection(self, app_id):
            self.initialized.append(app_id)

    calls = []
    vector = VectorClient()

    import services.rag.app.main as main

    config = type("Config", (), {"logging": LoggingConfig(), "database": object() if has_database else None})()

    def configure_app(app, config):
        calls.append("configure")
        app.state.config = config
        app.state.vector_client = vector

    def initialize_database(app):
        calls.append("initialize")

    def close_clients(app):
        calls.append("close")

    monkeypatch.setattr(main, "_configure_app", configure_app)
    monkeypatch.setattr(main, "_initialize_database", initialize_database)
    monkeypatch.setattr(main, "_close_clients", close_clients)
    monkeypatch.setattr(main, "load_app_config", lambda: config)

    async def run_lifespan():
        app = FastAPI()
        async with main.lifespan(app):
            assert app.state.config is config

    asyncio.run(run_lifespan())
    assert calls == (["configure", "initialize", "close"] if has_database else ["configure", "close"])
    assert vector.initialized == []


@pytest.mark.parametrize("has_database", [True, False])
def test_configure_app_uses_http_service_clients(monkeypatch, has_database):
    import services.rag.app.main as main

    database_calls = []

    class Database:
        def __init__(self, url, pool_size):
            database_calls.append(url)
            self.url = url
            self.pool_size = pool_size

    monkeypatch.setattr(main, "PgClient", Database)
    import httpx
    monkeypatch.setattr(httpx.Client, "get", lambda self, *args, **kwargs: httpx.Response(
        200, json={"capabilities": {"sparse": True, "rerank": True}},
        request=httpx.Request("GET", "http://inference:7001/ready"),
    ))

    config = parse_app_config({
        "search": {"rerank": True},
        "auth": {"admin": {"username": "admin", "password": "admin123"}},
        "database": {"provider": "postgres", "url": "postgresql://rag:rag@postgres:5432/rag"} if has_database else None,
        "services": {
            "parser": {"base_url": "http://parser:7000"},
            "inference": {"base_url": "http://inference:7001"},
            "vector": {"provider": "qdrant", "base_url": "http://qdrant:6333"},
        },
    })

    app = FastAPI()
    main._configure_app(app, config)

    assert isinstance(app.state.parser_client, HttpParserClient)
    assert isinstance(app.state.inference_client, HttpInferenceClient)
    assert app.state.inference_client.sparse is not None
    assert app.state.inference_client.rerank is not None
    assert isinstance(app.state.vector_client, QdrantVectorClient)
    if has_database:
        assert isinstance(app.state.db_client, Database)
        assert database_calls == [config.database.url]
    else:
        assert app.state.db_client is None
        assert database_calls == []
    assert app.state.search_pipeline is not None
    assert app.state.search_pipeline.rerank_client is app.state.inference_client.rerank
    app.state.parser_client.close()
    app.state.inference_client.close()


def test_initialize_database_does_not_fail_startup():
    import services.rag.app.main as main

    calls = []
    app = FastAPI()

    class Database:
        def initialize(self):
            calls.append("database")
            raise RuntimeError("database unavailable")

    app.state.db_client = Database()

    main._initialize_database(app)

    assert calls == ["database"]


def test_initialize_database_marks_interrupted_indexing_failed():
    import services.rag.app.main as main

    calls = []
    app = FastAPI()

    class Database:
        def initialize(self):
            calls.append("initialize")

        def mark_interrupted_indexing_failed(self):
            calls.append("mark_interrupted")
            return 2

    app.state.db_client = Database()

    main._initialize_database(app)

    assert calls == ["initialize", "mark_interrupted"]


def test_close_clients_closes_in_dependency_order():
    import services.rag.app.main as main

    calls = []
    app = FastAPI()

    class Client:
        def __init__(self, name):
            self.name = name

        def close(self):
            calls.append(self.name)

    app.state.parser_client = Client("parser")
    app.state.search_pipeline = Client("search")
    app.state.vector_client = Client("vector")
    app.state.inference_client = Client("inference")
    app.state.db_client = Client("database")
    app.state.ready = True

    main._close_clients(app)

    assert calls == ["parser", "search", "vector", "inference", "database"]
    assert app.state.ready is False
