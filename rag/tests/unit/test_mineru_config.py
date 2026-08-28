import json
import os
from pathlib import Path


def test_prepare_mineru_runtime_config_uses_current_models_dir(tmp_path, monkeypatch):
    from rag.parser import mineru

    mineru_dir = tmp_path / "models" / "mineru"
    pipeline_dir = mineru_dir / "pipeline"
    (pipeline_dir / "models").mkdir(parents=True)
    source_config = mineru_dir / "mineru.json"
    source_config.write_text(
        json.dumps({"models-dir": {"pipeline": "/stale/container/path", "vlm": ""}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(mineru, "MINERU_DIR", mineru_dir)
    monkeypatch.delenv("MINERU_TOOLS_CONFIG_JSON", raising=False)
    monkeypatch.delenv("PADDLE_PDX_CACHE_HOME", raising=False)

    mineru._prepare_mineru_runtime_config()
    mineru.prepare_paddle_runtime()

    runtime_config = Path(os.environ["MINERU_TOOLS_CONFIG_JSON"])
    assert runtime_config != source_config
    assert json.loads(runtime_config.read_text(encoding="utf-8"))["models-dir"]["pipeline"] == str(pipeline_dir)
    assert json.loads(source_config.read_text(encoding="utf-8"))["models-dir"]["pipeline"] == "/stale/container/path"
    assert os.environ["PADDLE_PDX_CACHE_HOME"].endswith("models/PaddlePaddle/PaddleOCR")
