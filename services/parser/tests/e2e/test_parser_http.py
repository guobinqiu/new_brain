import os
import socket
import subprocess
import sys
import time

import httpx
import pytest

from shared.paths import PROJECT_ROOT


pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def parser_http(tmp_path_factory):
    env = dict(os.environ, SERVICE_API_KEY="parser-e2e-key", ARK_API_KEY="parser-e2e-ark-key")
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


def test_upload_text_and_table_returns_normalized_blocks(parser_http):
    document = "hello parser\n\n| Name | Value |\n| --- | --- |\n| alpha | 1 |\n"

    response = parser_http.post(
        "/v1/parse/file", files={"file": ("sample.md", document.encode(), "text/markdown")},
        headers={"Authorization": "Bearer parser-e2e-key"},
    )

    assert response.status_code == 200
    assert response.json() == {"blocks": [
        {"type": "text", "text": "hello parser", "kind": "paragraph"},
        {"type": "table", "rows": [["Name", "Value"], ["alpha", "1"]]},
    ]}


def test_upload_txt_preserves_blank_line_paragraphs(parser_http):
    document = "第一段\n续行\n\n第二段"

    response = parser_http.post(
        "/v1/parse/file", files={"file": ("paragraphs.txt", document.encode("utf-8"), "text/plain")},
        headers={"Authorization": "Bearer parser-e2e-key"},
    )

    assert response.status_code == 200
    assert response.json() == {"blocks": [
        {"type": "text", "text": "第一段\n续行", "kind": "paragraph"},
        {"type": "text", "text": "第二段", "kind": "paragraph"},
    ]}


def test_upload_requires_service_api_key(parser_http):
    response = parser_http.post(
        "/v1/parse/file", files={"file": ("sample.txt", b"hello parser", "text/plain")},
    )
    assert response.status_code == 401


def test_markdown_structure_kinds_cross_http_boundary(parser_http):
    document = "# Title\n\nParagraph\n\n- Item\n\n```python\n    print(1)\n```\n\n> Quote\n"
    response = parser_http.post(
        "/v1/parse/file", files={"file": ("structure.md", document.encode(), "text/markdown")},
        headers={"Authorization": "Bearer parser-e2e-key"},
    )
    assert response.status_code == 200
    blocks = response.json()["blocks"]
    assert [block["kind"] for block in blocks] == ["heading", "paragraph", "list_item", "code", "text"]
    assert blocks[3]["text"] == "```python\n    print(1)\n```"
