from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


def test_convert_legacy_office_file_invokes_soffice(tmp_path, monkeypatch):
    from services.parser.common.office_convert import convert_legacy_office_file

    calls = []
    source = tmp_path / "demo.doc"
    source.write_bytes(b"legacy")

    def fake_run(cmd, check, capture_output, text):
        calls.append(cmd)
        output_dir = Path(cmd[cmd.index("--outdir") + 1])
        (output_dir / "demo.docx").write_bytes(b"converted")

    monkeypatch.setattr("subprocess.run", fake_run)

    with convert_legacy_office_file(str(source), ".docx") as converted:
        assert converted.name == "demo.docx"
        assert converted.read_bytes() == b"converted"

    assert calls == [[
        "soffice",
        "--headless",
        "--convert-to",
        "docx",
        "--outdir",
        str(converted.parent),
        str(source),
    ]]
