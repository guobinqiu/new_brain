import pytest


pytestmark = pytest.mark.unit


class FakeApplicationStore:
    def __init__(self, calls):
        self.calls = calls

    def add_common_documents(self, chunks, namespace="default"):
        self.calls.append(("common", chunks, namespace))
        return len(chunks)

    def add_scoped_documents(self, chunks, namespace="default", scope_id=None):
        self.calls.append(("scoped", chunks, namespace, scope_id))
        return len(chunks)


def test_upload_common_uses_common_store(monkeypatch, tmp_path):
    import main

    calls = []
    parse_calls = []
    parsed = [{"id": "chunk-1", "content": "content", "metadata": {"filename": "faq.txt"}}]
    fake_ocr = object()
    main.application.ocr = fake_ocr
    monkeypatch.setattr(main.application, "store", FakeApplicationStore(calls))
    monkeypatch.setattr(main, "_require_ready", lambda: None)
    monkeypatch.setattr(main, "parse_file", lambda path, original_filename=None, ocr=None: parse_calls.append((path, original_filename, ocr)) or parsed)

    path = tmp_path / "faq.txt"
    path.write_text("content", encoding="utf-8")

    result = main.index_chunks(
        str(path),
        filename="faq.txt",
        collection_type="common",
        namespace="tenant_a",
        scope_id=None,
    )

    assert result["collection_type"] == "common"
    assert result["namespace"] == "tenant_a"
    assert calls == [("common", parsed, "tenant_a")]
    assert parse_calls == [(str(path), "faq.txt", fake_ocr)]


def test_upload_scoped_requires_scope_and_uses_scoped_store(monkeypatch, tmp_path):
    import main

    calls = []
    parse_calls = []
    parsed = [{"id": "chunk-1", "content": "content", "metadata": {"filename": "faq.txt"}}]
    fake_ocr = object()
    main.application.ocr = fake_ocr
    monkeypatch.setattr(main.application, "store", FakeApplicationStore(calls))
    monkeypatch.setattr(main, "_require_ready", lambda: None)
    monkeypatch.setattr(main, "parse_file", lambda path, original_filename=None, ocr=None: parse_calls.append((path, original_filename, ocr)) or parsed)

    path = tmp_path / "faq.txt"
    path.write_text("content", encoding="utf-8")

    result = main.index_chunks(
        str(path),
        filename="faq.txt",
        collection_type="scoped",
        namespace="tenant_a",
        scope_id="scope_001",
    )

    assert result["collection_type"] == "scoped"
    assert result["scope_id"] == "scope_001"
    assert calls == [("scoped", parsed, "tenant_a", "scope_001")]
    assert parse_calls == [(str(path), "faq.txt", fake_ocr)]


def test_upload_scoped_without_scope_id_is_rejected(tmp_path):
    import main

    path = tmp_path / "faq.txt"
    path.write_text("content", encoding="utf-8")

    with pytest.raises(ValueError, match="scope_id"):
        main.index_chunks(
            str(path),
            filename="faq.txt",
            collection_type="scoped",
            namespace="tenant_a",
            scope_id=None,
        )
