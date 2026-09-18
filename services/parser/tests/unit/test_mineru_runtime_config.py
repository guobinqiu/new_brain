import json

import pytest


pytestmark = pytest.mark.unit


def test_mineru_runtime_config_uses_local_project_model_dir(monkeypatch, tmp_path):
    from services.parser.providers import mineru

    mineru_dir = tmp_path / "mineru"
    (mineru_dir / "pipeline" / "models").mkdir(parents=True)
    (mineru_dir / "mineru.json").write_text(
        json.dumps({
            "models-dir": {
                "pipeline": "/Users/example/.cache/huggingface/snapshots/hash",
                "vlm": "",
            },
            "model-source": "huggingface",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(mineru, "MINERU_DIR", mineru_dir)
    monkeypatch.setattr(mineru.tempfile, "gettempdir", lambda: str(tmp_path))

    mineru.prepare_mineru_runtime_config()

    runtime_config_path = tmp_path / "mineru_runtime_config.json"
    runtime_config = json.loads(runtime_config_path.read_text(encoding="utf-8"))
    assert runtime_config["models-dir"]["pipeline"] == str(mineru_dir / "pipeline")
    assert runtime_config["models-dir"]["vlm"] == ""
    assert runtime_config["model-source"] == "local"
