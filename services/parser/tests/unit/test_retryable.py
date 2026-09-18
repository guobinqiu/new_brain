import httpx
import pytest

from services.parser.providers.volcengine import _retryable_response


@pytest.mark.parametrize("status,code,expected", [
    (429, "RateLimitExceeded.EndpointRPMExceeded", False),
    (429, "RateLimitExceeded.EndpointTPMExceeded", False),
    (429, "ModelAccountRpmRateLimitExceeded", False),
    (429, "ModelAccountTpmRateLimitExceeded", False),
    (429, "APIAccountRpmRateLimitExceeded", False),
    (429, "AccountRateLimitExceeded", False),
    (429, "ServerOverloaded", False),
    (429, "RequestBurstTooFast", False),
    (429, "InflightBatchsizeExceeded", False),
    (500, "InternalServiceError", True),
    (429, "QuotaExceeded", False),
    (403, "ServerOverloaded", False),
    (500, "InvalidParameter", True),
    (429, "RateLimitExceeded.Unknown", False),
    (429, None, False),
    (429, [], False),
])
def test_retryable_uses_http_status(status, code, expected):
    assert _retryable_response(httpx.Response(status, json={"error": {"code": code}})) is expected


def test_html_and_missing_response_are_retryable_when_status_is_temporary():
    assert _retryable_response(httpx.Response(503, text="bad gateway")) is True
    assert _retryable_response(None) is True
