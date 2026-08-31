import os

import pytest

pytestmark = pytest.mark.unit


def test_unstructured_start_loads_hi_res_and_table_models(monkeypatch):
    from rag.parser import unstructured
    from rag.parser.unstructured import UnstructuredDocumentParser
    from rag.schema import UnstructuredParserConfig

    calls = []
    monkeypatch.setattr(unstructured, "_prepare_unstructured_runtime_config", lambda: calls.append("config"))
    monkeypatch.setattr(unstructured, "_load_unstructured_layout_model", lambda: calls.append("layout"), raising=False)
    monkeypatch.setattr(unstructured, "_load_unstructured_table_model", lambda: calls.append("table"), raising=False)

    parser = UnstructuredDocumentParser(UnstructuredParserConfig(strategy="hi_res", infer_table_structure=True))
    parser.start()

    assert parser.ready is True
    assert calls == ["config", "layout", "table"]


def test_unstructured_start_skips_model_load_for_fast_without_tables(monkeypatch):
    from rag.parser import unstructured
    from rag.parser.unstructured import UnstructuredDocumentParser
    from rag.schema import UnstructuredParserConfig

    calls = []
    monkeypatch.setattr(unstructured, "_prepare_unstructured_runtime_config", lambda: calls.append("config"))
    monkeypatch.setattr(unstructured, "_load_unstructured_layout_model", lambda: calls.append("layout"), raising=False)
    monkeypatch.setattr(unstructured, "_load_unstructured_table_model", lambda: calls.append("table"), raising=False)

    parser = UnstructuredDocumentParser(UnstructuredParserConfig(strategy="fast", infer_table_structure=False))
    parser.start()

    assert parser.ready is True
    assert calls == ["config"]


def test_unstructured_start_keeps_not_ready_when_model_load_fails(monkeypatch):
    from rag.parser import unstructured
    from rag.parser.unstructured import UnstructuredDocumentParser
    from rag.schema import UnstructuredParserConfig

    monkeypatch.setattr(unstructured, "_prepare_unstructured_runtime_config", lambda: None)

    def fail():
        raise RuntimeError("layout missing")

    monkeypatch.setattr(unstructured, "_load_unstructured_layout_model", fail, raising=False)
    monkeypatch.setattr(unstructured, "_load_unstructured_table_model", lambda: None, raising=False)

    parser = UnstructuredDocumentParser(UnstructuredParserConfig(strategy="hi_res", infer_table_structure=False))

    with pytest.raises(RuntimeError, match="layout missing"):
        parser.start()

    assert parser.ready is False


def test_unstructured_runtime_config_uses_local_hf_cache(monkeypatch, tmp_path):
    from rag.parser import unstructured

    model_config = tmp_path / "models" / "unstructured" / "yolox.json"
    model_config.parent.mkdir(parents=True)
    model_config.write_text("{}", encoding="utf-8")
    hf_cache = tmp_path / "models" / "huggingface" / "hub"
    hf_cache.mkdir(parents=True)

    monkeypatch.setattr(unstructured, "UNSTRUCTURED_MODEL_CONFIG", model_config)
    monkeypatch.setattr(unstructured, "HF_CACHE_DIR", hf_cache, raising=False)
    monkeypatch.setattr(unstructured, "TABLE_STRUCTURE_MODEL_CACHE", tmp_path / "missing-table-model", raising=False)
    monkeypatch.delenv("UNSTRUCTURED_DEFAULT_MODEL_NAME", raising=False)
    monkeypatch.delenv("UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH", raising=False)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)

    unstructured._prepare_unstructured_runtime_config()

    assert os.environ["UNSTRUCTURED_DEFAULT_MODEL_NAME"] == "yolox"
    assert os.environ["UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH"] == str(model_config)
    assert os.environ["HF_HOME"] == str(hf_cache.parent)
    assert os.environ["HUGGINGFACE_HUB_CACHE"] == str(hf_cache)
    assert os.environ["HF_HUB_OFFLINE"] == "1"

    from huggingface_hub import constants
    from transformers.utils import hub

    assert constants.HF_HOME == str(hf_cache.parent)
    assert constants.HF_HUB_CACHE == str(hf_cache)
    assert constants.HF_HUB_OFFLINE is True
    assert hub.is_offline_mode() is True


def test_unstructured_table_load_uses_local_table_snapshot(monkeypatch, tmp_path):
    import sys
    import types

    from rag.parser import unstructured

    table_cache = tmp_path / "models--microsoft--table-transformer-structure-recognition"
    snapshot = table_cache / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (table_cache / "refs").mkdir()
    (table_cache / "refs" / "main").write_text("abc123", encoding="utf-8")

    calls = []
    tables = types.SimpleNamespace(DEFAULT_MODEL="microsoft/table-transformer-structure-recognition", load_agent=lambda: calls.append("load_agent"))
    models = types.ModuleType("unstructured_inference.models")
    models.tables = tables
    package = types.ModuleType("unstructured_inference")
    package.models = models
    monkeypatch.setitem(sys.modules, "unstructured_inference", package)
    monkeypatch.setitem(sys.modules, "unstructured_inference.models", models)
    monkeypatch.setattr(unstructured, "TABLE_STRUCTURE_MODEL_CACHE", table_cache, raising=False)

    unstructured._load_unstructured_table_model()

    assert tables.DEFAULT_MODEL == str(snapshot)
    assert calls == ["load_agent"]
