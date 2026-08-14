import re

import pytest
from datetime import timedelta


pytestmark = pytest.mark.unit


def test_index_chunks_returns_file_id_after_sync_index(monkeypatch, tmp_path):
    import main

    indexed = []
    monkeypatch.setattr(main, "_require_ready", lambda: None)
    monkeypatch.setattr(main, "create_file_id", lambda: "abc123")
    monkeypatch.setattr(main, "index_file", lambda application, file_id, path, filename, extra_metadata=None: indexed.append((application, file_id, path, filename, extra_metadata)) or 3)

    path = tmp_path / "faq.txt"
    path.write_text("content", encoding="utf-8")

    result = main.index_chunks(str(path), filename="faq.txt")

    assert result == {"file_id": "abc123"}
    assert indexed == [(main.application, "abc123", path, "faq.txt", None)]


def test_index_request_accepts_optional_file_id():
    import main

    schema = main.ObjectIndexRequest.model_json_schema()

    assert "file_id" in schema["properties"]


def test_generated_file_id_is_uuid_hex_without_prefix_or_dash():
    from indexing.service import create_file_id

    file_id = create_file_id()

    assert re.fullmatch(r"[0-9a-f]{32}", file_id)


def test_storage_presign_uses_minio_and_public_endpoint(monkeypatch):
    import main

    class FakeMinio:
        def presigned_get_object(self, bucket, object_name, expires):
            assert bucket == "rag-dev"
            assert object_name == "docs/a.pdf"
            assert expires == timedelta(seconds=120)
            return "http://minio:9000/rag-dev/docs/a.pdf?token=abc"

    monkeypatch.setattr(main, "_minio_client", lambda: FakeMinio())
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.delenv("S3_PUBLIC_ENDPOINT_URL", raising=False)

    result = main.presign_object(main.PresignRequest(s3_url="s3://rag-dev/docs/a.pdf", expires_in=120))

    assert result == {"presigned_url": "http://minio:9000/rag-dev/docs/a.pdf?token=abc"}


def test_presign_route_is_top_level_api_endpoint():
    import main

    paths = {route.path for route in main.app.routes}

    assert "/api/presign" in paths


def test_upload_file_to_storage_puts_object_in_bucket(monkeypatch):
    import main

    calls = []

    class FakeMinio:
        def bucket_exists(self, bucket):
            calls.append(("bucket_exists", bucket))
            return False

        def make_bucket(self, bucket):
            calls.append(("make_bucket", bucket))

        def put_object(self, bucket, object_name, data, length, content_type):
            calls.append(("put_object", bucket, object_name, data.read(), length, content_type))

    monkeypatch.setattr(main, "_minio_client", lambda: FakeMinio())
    monkeypatch.setattr(main, "create_file_id", lambda: "abc123")
    monkeypatch.setenv("S3_BUCKET", "rag-dev")

    result = main._upload_file_to_storage("docs/a.txt", b"hello", "text/plain")

    assert result == "s3://rag-dev/uploads/abc123/a.txt"
    assert calls == [
        ("bucket_exists", "rag-dev"),
        ("make_bucket", "rag-dev"),
        ("put_object", "rag-dev", "uploads/abc123/a.txt", b"hello", 5, "text/plain"),
    ]
