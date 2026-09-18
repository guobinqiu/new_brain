import pytest


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def config_environment(monkeypatch):
    monkeypatch.setenv("RAG_ADMIN_PASSWORD", "dummy-admin-password")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RAG_APPS", raising=False)
    for name in ("SERVICE_API_KEY", "PARSER_API_KEY", "INFERENCE_API_KEY", "SILICONFLOW_CN_API_KEY", "SILICONFLOW_INTL_API_KEY", "QDRANT_API_KEY", "MILVUS_TOKEN", "QDRANT_CLOUD_API_KEY", "MILVUS_CLOUD_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {
        "PARSER_BASE_URL": "http://wrong-parser:7000",
        "INFERENCE_BASE_URL": "http://wrong-inference:7001",
        "QDRANT_BASE_URL": "http://wrong-qdrant:6333",
        "MILVUS_BASE_URL": "http://wrong-milvus:19530",
        "QDRANT_CLOUD_BASE_URL": "https://wrong-qdrant-cloud.example",
        "MILVUS_CLOUD_BASE_URL": "https://wrong-milvus-cloud.example",
        "S3_ENDPOINT_URL": "https://wrong-storage.example:9000",
        "LOKI_URL": "http://wrong-logs:3100",
    }.items():
        monkeypatch.setenv(name, value)


def _base_config(vector: str = "qdrant") -> dict:
    vector_urls = {
        "qdrant": "http://qdrant:6333",
        "milvus": "http://milvus:19530",
        "qdrant_cloud": "https://qdrant_cloud.example",
        "milvus_cloud": "https://milvus_cloud.example",
    }
    vector_config = {
        "enable": True,
        "base_url": vector_urls[vector],
        "query_timeout": 10,
        "write_timeout": 60,
        "init_timeout": 120,
        "drop_timeout": 180,
    }
    return {
        "search": {"top_k": 5, "rerank_fetch_k": 20, "rerank": True},
        "auth": {"admin": {"username": "admin"}},
        "storage": {"endpoint_url": "https://storage.example:9000", "bucket": "documents", "download_timeout": 44},
        "logging": {"level": "WARNING", "loki_url": "http://logs:3100"},
        "api": {
            "index_timeout": 222,
            "batch_index": {
                "base_url": "http://rag:6000",
                "max_files": 10,
                "max_concurrency": 5,
            },
        },
        "db": {
            "postgres": {
                "enable": True,
                "url": "postgresql://rag:rag@postgres:5432/rag",
                "pool_size": 5,
                "retry": {"max_attempts": 3, "interval_seconds": 0.5},
            },
        },
        "parser": {"base_url": "http://parser:7000", "timeout": 360},
        "inference": {
            "base_url": "http://inference:7001",
            "embedding": {"timeout": 150},
            "rerank": {"timeout": 45},
        },
        "vector_db": {vector: vector_config},
    }


def test_load_config_file_reads_service_bound_qdrant_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PARSER_TIMEOUT", "1")
    monkeypatch.setenv("INFERENCE_TIMEOUT", "1")
    monkeypatch.setenv("VECTOR_DB_TIMEOUT", "1")
    import yaml
    from services.rag.core.loader import load_config_file

    path = tmp_path / "rag.yaml"
    path.write_text(yaml.safe_dump(_base_config("qdrant")), encoding="utf-8")

    config = load_config_file(path)

    assert config.services.parser.timeout == 360
    assert config.services.inference.embedding.timeout == 150
    assert config.services.inference.rerank.timeout == 45
    assert config.services.vector.query_timeout == 10
    assert config.services.vector.write_timeout == 60
    assert config.services.vector.init_timeout == 120
    assert config.services.vector.drop_timeout == 180
    assert config.name == "rag"
    assert config.services.vector.provider == "qdrant"
    assert config.services.vector.base_url == "http://qdrant:6333"
    assert config.services.parser.base_url == "http://parser:7000"
    assert config.services.inference.base_url == "http://inference:7001"
    assert config.database.provider == "postgres"
    assert config.database.url == "postgresql://rag:rag@postgres:5432/rag"
    assert config.database.retry.max_attempts == 3
    assert config.database.retry.interval_seconds == 0.5
    assert config.search.top_k == 5
    assert config.search.rerank_fetch_k == 20
    assert config.search.rerank is True
    assert config.storage.endpoint_url == "https://storage.example:9000"
    assert config.storage.bucket == "documents"
    assert config.storage.download_timeout == 44
    assert config.logging.loki_url == "http://logs:3100"
    assert config.api.index_timeout == 222
    assert config.api.batch_index.base_url == "http://rag:6000"
    assert config.api.batch_index.max_files == 10
    assert config.api.batch_index.max_concurrency == 5
    assert config.auth.admin.password == "dummy-admin-password"


def test_load_config_file_reads_service_bound_milvus_config(tmp_path):
    import yaml
    from services.rag.core.loader import load_config_file

    raw = _base_config("milvus")
    path = tmp_path / "milvus.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    config = load_config_file(path)

    assert config.services.vector.provider == "milvus"
    assert config.services.vector.base_url == "http://milvus:19530"


@pytest.mark.parametrize("selected,provider", [("qdrant_cloud", "qdrant"), ("milvus_cloud", "milvus")])
def test_cloud_vector_selection_keeps_cloud_endpoint(tmp_path, monkeypatch, selected, provider):
    import yaml
    from services.rag.core.loader import load_config_file

    monkeypatch.setenv("MILVUS_CLOUD_TOKEN", "cloud-token")
    monkeypatch.setenv("QDRANT_CLOUD_API_KEY", "cloud-key")
    raw = _base_config()
    for name in ("qdrant", "milvus", "qdrant_cloud", "milvus_cloud"):
        base_url = f"https://{name}.example" if name.endswith("_cloud") else f"http://{name}:6333"
        raw["vector_db"][name] = {
            "enable": name == selected,
            "base_url": base_url,
            "query_timeout": 10,
            "write_timeout": 60,
            "init_timeout": 120,
            "drop_timeout": 180,
            "retry": {"max_attempts": 3, "interval_seconds": 0.5},
        }
    path = tmp_path / "cloud.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    config = load_config_file(path)

    assert config.services.vector.provider == provider
    assert config.services.vector.base_url == f"https://{selected}.example"
    assert config.services.vector.query_timeout == 10
    assert config.services.vector.write_timeout == 60
    assert config.services.vector.init_timeout == 120
    assert config.services.vector.drop_timeout == 180
    assert config.services.vector.retry.max_attempts == 3
    assert config.services.vector.retry.interval_seconds == 0.5
    assert config.services.vector.token == ("cloud-token" if provider == "milvus" else None)
    assert config.services.vector.api_key == ("cloud-key" if provider == "qdrant" else None)
    options = config.available_components["vector"]
    assert len(options) == 4
    assert [item["name"] for item in options if item["active"]] == [selected]








def test_load_app_config_uses_project_yaml_by_default(tmp_path, monkeypatch):
    import yaml
    from services.rag.core import loader

    path = tmp_path / "services/rag/config/rag.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(_base_config("milvus")), encoding="utf-8")
    monkeypatch.setattr(loader, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("RAG_CONFIG_FILE", raising=False)

    config = loader.load_app_config()

    assert config.name == "rag"
    assert config.services.vector.provider == "milvus"


def test_load_app_config_reads_isolated_yaml_and_database_secret(tmp_path, monkeypatch):
    import yaml
    from services.rag.core.loader import load_app_config

    raw = _base_config("milvus")
    raw["db"]["postgres"]["url"] = ""
    raw["db"]["postgres"]["pool_size"] = 7
    path = tmp_path / "isolated.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    monkeypatch.setenv("RAG_CONFIG_FILE", str(path))
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:dummy@db:5432/test")

    config = load_app_config()

    assert config.name == "isolated"
    assert config.database.url == "postgresql://test:dummy@db:5432/test"
    assert config.database.pool_size == 7


def test_load_config_file_selects_enabled_database(tmp_path, monkeypatch):
    import yaml
    from services.rag.core.loader import load_config_file

    monkeypatch.setenv("RAG_APPS", "not-json")
    raw = _base_config("qdrant")
    path = tmp_path / "rag.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    config = load_config_file(path)

    assert config.database.provider == "postgres"
    assert config.database.url == "postgresql://rag:rag@postgres:5432/rag"
    assert config.auth.apps == []
    database_options = {item["name"]: item for item in config.available_components["database"]}
    assert database_options["postgres"]["active"] is True


@pytest.mark.parametrize("database", [None, {}, {"postgres": {"enable": False}}])
def test_load_config_without_database_reads_apps_and_allows_core_only_runtime(tmp_path, monkeypatch, database):
    import json
    import yaml
    from services.rag.core.loader import load_config_file

    raw = _base_config("qdrant")
    raw["db"] = database
    apps = [{"app_id": "tenant_a", "api_key": "key-a"}, {"app_id": "tenant_b", "api_key": "key-b"}]
    monkeypatch.setenv("RAG_APPS", json.dumps(apps))
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused:dummy@unused/db")
    monkeypatch.delenv("RAG_ADMIN_PASSWORD")
    path = tmp_path / "rag.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    config = load_config_file(path)

    assert config.database is None
    assert [(app.app_id, app.api_key) for app in config.auth.apps] == [("tenant_a", "key-a"), ("tenant_b", "key-b")]
    assert config.auth.admin.password == ""
    assert config.storage.endpoint_url == "https://storage.example:9000"
    assert config.storage.bucket == "documents"
    assert config.logging.loki_url == "http://logs:3100"






def test_load_config_file_selects_one_enabled_vector_backend(tmp_path):
    import yaml
    from services.rag.core.loader import load_config_file

    raw = _base_config("qdrant")
    raw["vector_db"]["qdrant"] = {"enable": False}
    raw["vector_db"]["milvus"] = {"enable": True, "base_url": "http://milvus:19530"}
    path = tmp_path / "rag.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    config = load_config_file(path)

    assert config.services.vector.provider == "milvus"
    assert config.services.vector.base_url == "http://milvus:19530"
    vector_options = {item["name"]: item for item in config.available_components["vector"]}
    assert vector_options["qdrant"] == {"name": "qdrant", "model_name": None, "active": False}
    assert vector_options["milvus"] == {"name": "milvus", "model_name": None, "active": True}


def test_load_config_rejects_no_enabled_vector(tmp_path):
    import yaml
    from services.rag.core.loader import load_config_file

    raw = _base_config("qdrant")
    raw["vector_db"]["qdrant"] = {"enable": False, "base_url": "http://qdrant:6333"}
    raw["vector_db"]["milvus"] = {"enable": False, "base_url": "http://milvus:19530"}
    path = tmp_path / "rag.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="vector backend must enable exactly one component"):
        load_config_file(path)


def test_load_config_rejects_multiple_enabled_vectors(tmp_path):
    import yaml
    from services.rag.core.loader import load_config_file

    raw = _base_config("qdrant")
    raw["vector_db"]["qdrant"] = {"enable": True, "base_url": "http://qdrant:6333"}
    raw["vector_db"]["milvus"] = {"enable": True, "base_url": "http://milvus:19530"}
    path = tmp_path / "rag.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="vector backend must enable exactly one component"):
        load_config_file(path)


@pytest.mark.parametrize("vector", ["unsupported_vector"])
def test_load_config_rejects_unknown_vector_backends(tmp_path, vector):
    import yaml
    from services.rag.core.loader import load_config_file

    raw = _base_config("qdrant")
    raw["vector_db"]["qdrant"]["provider"] = vector
    path = tmp_path / "removed.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ValueError):
        load_config_file(path)
