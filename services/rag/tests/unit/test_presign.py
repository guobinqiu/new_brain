import pytest

from services.rag.core import presign


pytestmark = pytest.mark.unit


def test_request_template_keeps_query_and_body_separate():
    config = '''{
        "url": "https://example.com/presign",
        "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "params": {"app": {{ app_id | tojson }}},
        "body": {"url": {{ s3_url | tojson }}, "id": {{ file_id | tojson }}}
    }'''
    request = presign.build_request(config, {"app_id": "a", "s3_url": "s3://bucket/a b", "file_id": "f"})
    assert request["params"] == {"app": "a"}
    assert request["json"] == {"url": "s3://bucket/a b", "id": "f"}


def test_form_body_and_nested_response_url():
    request = presign.build_request('''{
        "url": "https://example.com", "method": "POST",
        "headers": {"Content-Type": "application/x-www-form-urlencoded"},
        "body": {"file": {{ filename | tojson }}}
    }''', {"filename": 'report "final".pdf'})
    assert request["data"] == {"file": 'report "final".pdf'}
    assert presign.response_url({"data": {"download_url": "https://s3.example.com/a"}}, "data.download_url") == "https://s3.example.com/a"
