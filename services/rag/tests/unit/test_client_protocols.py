import pytest


pytestmark = pytest.mark.unit


def test_http_clients_satisfy_protocols():
    from services.rag.clients.inference import HttpInferenceClient
    from services.rag.clients.inference.base import InferenceClient
    from services.rag.clients.parser import HttpParserClient
    from services.rag.clients.parser.base import ParserClient

    assert ParserClient in HttpParserClient.__bases__
    assert InferenceClient in HttpInferenceClient.__bases__


def test_pg_client_satisfies_db_protocol():
    from services.rag.clients.db import PgClient
    from services.rag.clients.db.base import DbClient

    assert DbClient in PgClient.__bases__
