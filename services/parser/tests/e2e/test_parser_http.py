import os
import socket
import subprocess
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from shared.paths import PROJECT_ROOT


pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def parser_http(tmp_path_factory):
    env = dict(os.environ, SERVICE_API_KEY="parser-e2e-key", ARK_API_KEY="parser-e2e-ark-key", MINERU_API_KEY="parser-e2e-mineru-key")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        log_path = tmp_path_factory.mktemp("parser-http") / "server.log"
        with log_path.open("w+") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "services.parser.app.main:app", "--fd", str(listener.fileno())],
                cwd=PROJECT_ROOT, env=env, pass_fds=(listener.fileno(),), stdout=log, stderr=log,
            )
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as client:
                    deadline = time.monotonic() + 180
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            pytest.fail(f"Parser exited during startup: {log_path.read_text()}")
                        try:
                            if client.get("/health", timeout=1).status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        time.sleep(0.2)
                    else:
                        pytest.fail(f"Parser startup timed out: {log_path.read_text()}")
                    yield client
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


@pytest.fixture
def source_url():
    documents = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = documents.get(self.path)
            self.send_response(200 if body is not None else 404)
            self.end_headers()
            self.wfile.write(body if body is not None else b"missing")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def publish(name, content):
        documents["/" + name] = content.encode("utf-8")
        return f"http://127.0.0.1:{server.server_port}/{name}"

    try:
        yield publish
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_url_text_and_table_returns_normalized_blocks(parser_http, source_url):
    document = "hello parser\n\n| Name | Value |\n| --- | --- |\n| alpha | 1 |\n"

    response = parser_http.post(
        "/v1/parse/file", json={"filename": "sample.md", "presigned_url": source_url("sample.md", document)},
        headers={"Authorization": "Bearer parser-e2e-key"},
    )

    assert response.status_code == 200
    assert response.json() == {"file_size": len(document.encode()), "blocks": [
        {"type": "text", "text": "hello parser", "kind": "paragraph"},
        {"type": "table", "rows": [["Name", "Value"], ["alpha", "1"]]},
    ]}


def test_url_txt_preserves_blank_line_paragraphs(parser_http, source_url):
    document = "第一段\n续行\n\n第二段"

    response = parser_http.post(
        "/v1/parse/file", json={"filename": "paragraphs.txt", "presigned_url": source_url("paragraphs.txt", document)},
        headers={"Authorization": "Bearer parser-e2e-key"},
    )

    assert response.status_code == 200
    assert response.json() == {"file_size": len(document.encode()), "blocks": [
        {"type": "text", "text": "第一段\n续行", "kind": "paragraph"},
        {"type": "text", "text": "第二段", "kind": "paragraph"},
    ]}


def test_upload_requires_service_api_key(parser_http):
    response = parser_http.post(
        "/v1/parse/file", json={"filename": "sample.txt", "presigned_url": "https://source/sample.txt"},
    )
    assert response.status_code == 401


def test_markdown_structure_kinds_cross_http_boundary(parser_http, source_url):
    document = "# Title\n\nParagraph\n\n- Item\n\n```python\n    print(1)\n```\n\n> Quote\n"
    response = parser_http.post(
        "/v1/parse/file", json={"filename": "structure.md", "presigned_url": source_url("structure.md", document)},
        headers={"Authorization": "Bearer parser-e2e-key"},
    )
    assert response.status_code == 200
    blocks = response.json()["blocks"]
    assert [block["kind"] for block in blocks] == ["heading", "paragraph", "list_item", "code", "text"]
    assert blocks[3]["text"] == "```python\n    print(1)\n```"
