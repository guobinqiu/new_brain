from dataclasses import replace

import pytest


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("database_url, displayed_connection", [
    (
        "postgresql://rag:dummy%40password@postgres:5432/rag?sslpassword=tls%20secret&sslmode=require",
        {"user": "rag", "password": "***", "host": "postgres", "port": "5432", "dbname": "rag", "sslpassword": "***", "sslmode": "require"},
    ),
    (
        "host=postgres dbname=rag user=rag password='dummy password' sslpassword='tls secret' passfile=/tmp/credentials sslkey=/tmp/private.key",
        {"host": "postgres", "dbname": "rag", "user": "rag", "password": "***", "sslpassword": "***", "passfile": "***", "sslkey": "***"},
    ),
    (
        "postgresql://rag@postgres:5432/rag",
        {"user": "rag", "host": "postgres", "port": "5432", "dbname": "rag"},
    ),
])
def test_config_payload_includes_rerank_defaults_and_redacted_database(database_url, displayed_connection):
    from psycopg.conninfo import conninfo_to_dict
    from shared.config import parse_app_config
    from services.rag.core.api.services.config import config_payload

    config = parse_app_config({
        "search": {"top_k": 5, "rerank_fetch_k": 20, "rerank": True},
        "auth": {"admin": {"username": "admin", "password": "admin123"}},
        "database": {"provider": "postgres", "url": database_url},
        "services": {
            "parser": {"base_url": "http://parser:7000"},
            "inference": {"base_url": "http://inference:7001"},
            "vector": {"provider": "qdrant", "base_url": "http://qdrant:6333"},
        },
    })
    state = type(
        "State",
        (),
        {
            "config": replace(config, name="qdrant"),
            "config_name": "qdrant",
            "vector_client": object(),
            "inference_client": type("Inference", (), {"rerank": object()})(),
        },
    )()

    payload = config_payload(state)

    assert payload["top_k"] == 5
    assert payload["rerank"] is True
    assert payload["rerank_available"] is True
    assert payload["rerank_fetch_k"] == 20
    assert payload["hybrid"] == {"rrf_k": 60}
    database = payload["services"]["database"]
    assert database["provider"] == "postgres"
    assert database["pool_size"] == 5
    assert conninfo_to_dict(database["url"]) == displayed_connection
    assert state.config.database.url == database_url
