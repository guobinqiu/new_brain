import json
from contextlib import nullcontext
from unittest.mock import Mock

from services.rag.clients.db.postgres import PgClient
from services.rag.core.api.services.files import _file_error


def test_error_json_is_not_truncated(monkeypatch):
    connection = Mock()
    pool = Mock()
    pool.connection.return_value = nullcontext(connection)
    client = PgClient("unused")
    monkeypatch.setattr(client, "_get_pool", lambda: pool)
    error = {"error": "original " * 1000, "service": "parser", "retryable": False, "traceId": "a" * 32}
    client.mark_file_failed("app", "file", json.dumps(error))
    assert json.loads(connection.execute.call_args.args[1][0]) == error
    assert _file_error(connection.execute.call_args.args[1][0]) == error


def test_old_error_text_is_not_exposed():
    assert _file_error("old raw database exception") is None
    assert _file_error(None) is None


def test_old_error_json_has_unknown_service():
    error = {"error": "old error", "retryable": False, "traceId": None}
    assert _file_error(json.dumps(error)) == {**error, "service": None}
