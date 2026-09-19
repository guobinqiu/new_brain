import httpx
import pytest

from shared.upstream import upstream_error, internal_error


def response_error(status, **kwargs):
    request = httpx.Request("POST", "https://provider.test/api", headers={"Authorization": "Bearer actual-private-key"})
    response = httpx.Response(status, request=request, **kwargs)
    return httpx.HTTPStatusError("failed", request=request, response=response)


@pytest.mark.parametrize("status", [400, 401, 402, 403, 429, 500])
@pytest.mark.parametrize("nested", [True, False])
def test_external_message_and_http_status(status, nested):
    payload = {"code": "provider-code", "message": "Model does not support dimensions"}
    error = upstream_error("inference", response_error(status, json={"error": payload} if nested else payload))
    assert error.status_code == 502
    assert error.error == "Model does not support dimensions"


@pytest.mark.parametrize("payload", [{"message": {}}, {}])
def test_unusable_message_falls_back(payload):
    exc = response_error(500, json=payload)
    assert upstream_error("parser", exc).error == exc.response.text


def test_non_json_falls_back():
    assert upstream_error("parser", response_error(500, text="<html>error</html>")).error == "<html>error</html>"


def test_internal_non_json_error_keeps_original_body():
    assert internal_error("parser", response_error(500, text="upstream connection closed")).error == "upstream connection closed"


@pytest.mark.parametrize("message", ["", "  \n original message  ", "<html>gateway error</html>", "Traceback (most recent call last): secret", "x" * 2000, "Invalid actual-private-key; api_key=other-secret; Bearer third-secret; https://host/file?signature=secret"])
def test_external_message_is_unchanged(message):
    error = upstream_error("inference", response_error(400, json={"message": message}))
    assert error.error == message


def test_internal_error_is_preserved():
    detail = {"error": "Balance insufficient", "service": "provider", "retryable": False, "traceId": "a" * 32}
    assert internal_error("inference", response_error(502, json=detail)).detail() == detail


def test_network_error_identifies_target_service():
    assert upstream_error("parser", httpx.ConnectError("connect failed")).detail()["service"] == "parser"


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_unknown_external_error_is_not_retryable(status):
    assert upstream_error("parser", response_error(status, json={"error": {"code": "unknown"}})).retryable is False


def test_network_error_is_retryable():
    try:
        raise httpx.ConnectError("connect failed")
    except httpx.ConnectError as exc:
        assert upstream_error("parser", exc).retryable is True
