import pytest


pytestmark = pytest.mark.unit


def test_download_model_specs_include_planned_bge_m3_and_rerankers():
    import download_models

    sources = {spec.source for spec in download_models.MODEL_SPECS}
    local_dirs = {spec.local_dir for spec in download_models.MODEL_SPECS}

    assert "BAAI/bge-m3" in sources
    assert "BAAI/bge-reranker-v2-m3" in sources
    assert "BAAI/bge-reranker-large" in sources
    assert download_models.BGE_M3_MODEL_DIR in local_dirs
    assert download_models.RERANKER_M3_MODEL_DIR in local_dirs
    assert download_models.RERANKER_LARGE_MODEL_DIR in local_dirs


def test_large_planned_models_download_only_required_runtime_files():
    import download_models

    specs = {spec.source: spec for spec in download_models.MODEL_SPECS}

    bge_m3_patterns = specs["BAAI/bge-m3"].allow_patterns
    assert bge_m3_patterns is not None
    assert "pytorch_model.bin" in bge_m3_patterns
    assert "model.onnx" not in bge_m3_patterns
    assert "model.onnx_data" not in bge_m3_patterns

    reranker_large_patterns = specs["BAAI/bge-reranker-large"].allow_patterns
    assert reranker_large_patterns is not None
    assert "model.safetensors" in reranker_large_patterns
    assert "pytorch_model.bin" not in reranker_large_patterns
    assert "model.onnx" not in reranker_large_patterns
    assert "model.onnx_data" not in reranker_large_patterns

    reranker_m3_patterns = specs["BAAI/bge-reranker-v2-m3"].allow_patterns
    assert reranker_m3_patterns is not None
    assert "model.safetensors" in reranker_m3_patterns
    assert "pytorch_model.bin" not in reranker_m3_patterns
    assert "model.onnx" not in reranker_m3_patterns
    assert "model.onnx_data" not in reranker_m3_patterns
