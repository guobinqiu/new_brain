import pytest

from services.rag.tests.fixtures.database import isolated_pg


pytestmark = pytest.mark.integration


def test_template_and_failed_file_claim(isolated_pg):
    db = isolated_pg
    credential = db.create_app("tenant")
    from services.rag.core.presign import render_config

    initial = render_config(db.get_presign_config("tenant"), {"s3_url": "s3://bucket/report.pdf"})
    assert initial["url"] == "http://127.0.0.1:6000/api/v1/rag/presign"
    assert initial["headers"]["Authorization"] == f"Bearer {credential.api_key}"
    assert initial["body"] == {"s3_url": "s3://bucket/report.pdf"}
    template = '{"body": {"url": {{ s3_url | tojson }}}}'
    assert db.set_presign_config("tenant", template)
    assert db.get_presign_config("tenant") == template
    db.create_file("tenant", "original", "report.pdf", "s3://bucket/report.pdf")
    db.mark_file_failed("tenant", "original", '{"error":"failed","retryable":true,"traceId":"t"}')
    assert db.get_file("tenant", "original").status == "failed"
    assert db.get_file("other", "original") is None
    assert not db.claim_file_retry("other", "original")
    assert db.claim_file_retry("tenant", "original")
    assert not db.claim_file_retry("tenant", "original")
    assert db.get_file("tenant", "original").status == "indexing"
