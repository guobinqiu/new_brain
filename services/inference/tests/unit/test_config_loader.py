from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.unit


def _write_config(tmp_path, raw: dict) -> Path:
    path = tmp_path / "inference.yaml"
    path.write_text(yaml.safe_dump({"embedded": {"enable": True, **raw}}), encoding="utf-8")
    return path


def test_load_inference_config_selects_one_enabled_dense(tmp_path):
    from services.inference.app.config import load_inference_config

    path = _write_config(tmp_path, {
        "dense": {
            "bge_m3": {"enable": False, "model_name": "BAAI/bge-m3"},
            "bge_base": {"enable": True, "model_name": "BAAI/bge-base-zh-v1.5", "batch_size": 8, "release_memory": "after_call"},
        },
        "sparse": {
            "bge_m3": {"enable": False, "model_name": "BAAI/bge-m3"},
        },
        "rerank": None,
    })

    config = load_inference_config(path)

    assert config.dense.name == "bge_base"
    assert config.dense.model_name == "BAAI/bge-base-zh-v1.5"
    assert config.dense.model_path.endswith("models/BAAI/bge-base-zh-v1.5")
    assert config.dense.batch_size == 8
    assert config.dense.release_memory == "after_call"
    assert config.sparse is None
    assert config.rerank is None


def test_load_inference_config_selects_optional_sparse(tmp_path):
    from services.inference.app.config import load_inference_config

    path = _write_config(tmp_path, {
        "dense": {
            "bge_base": {"enable": True, "model_name": "BAAI/bge-base-zh-v1.5"},
        },
        "sparse": {
            "bge_m3": {"enable": True, "model_name": "BAAI/bge-m3", "batch_size": 2, "release_memory": "per_batch"},
        },
    })

    config = load_inference_config(path)

    assert config.sparse.name == "bge_m3"
    assert config.sparse.model_name == "BAAI/bge-m3"
    assert config.sparse.model_path.endswith("models/BAAI/bge-m3")
    assert config.sparse.batch_size == 2
    assert config.sparse.release_memory == "per_batch"


def test_load_inference_config_reads_explicit_config_file(tmp_path):
    from services.inference.app.config import load_inference_config

    path = _write_config(tmp_path, {
        "dense": {
            "bge_m3": {"enable": True, "model_name": "BAAI/bge-m3"},
            "bge_base": {"enable": False, "model_name": "BAAI/bge-base-zh-v1.5"},
        },
    })

    config = load_inference_config(path)

    assert config.dense.name == "bge_m3"
    assert config.dense.model_name == "BAAI/bge-m3"


def test_load_inference_config_rejects_no_enabled_dense(tmp_path):
    from services.inference.app.config import load_inference_config

    path = _write_config(tmp_path, {
        "dense": {
            "bge_m3": {"enable": False, "model_name": "BAAI/bge-m3"},
            "bge_base": {"enable": False, "model_name": "BAAI/bge-base-zh-v1.5"},
        },
    })

    with pytest.raises(ValueError, match="dense must enable exactly one component"):
        load_inference_config(path)


def test_load_inference_config_rejects_multiple_enabled_dense(tmp_path):
    from services.inference.app.config import load_inference_config

    path = _write_config(tmp_path, {
        "dense": {
            "bge_m3": {"enable": True, "model_name": "BAAI/bge-m3"},
            "bge_base": {"enable": True, "model_name": "BAAI/bge-base-zh-v1.5"},
        },
    })

    with pytest.raises(ValueError, match="dense must enable exactly one component"):
        load_inference_config(path)


def test_load_inference_config_allows_no_enabled_rerank(tmp_path):
    from services.inference.app.config import load_inference_config

    path = _write_config(tmp_path, {
        "dense": {"name": "bge_m3", "model_name": "BAAI/bge-m3"},
        "rerank": {
            "bge_m3": {"enable": False, "model_name": "BAAI/bge-reranker-v2-m3"},
            "bge_base": {"enable": False, "model_name": "BAAI/bge-reranker-base"},
        },
    })

    config = load_inference_config(path)

    assert config.rerank is None


def test_load_inference_config_rejects_multiple_enabled_rerank(tmp_path):
    from services.inference.app.config import load_inference_config

    path = _write_config(tmp_path, {
        "dense": {"name": "bge_m3", "model_name": "BAAI/bge-m3"},
        "rerank": {
            "bge_m3": {"enable": True, "model_name": "BAAI/bge-reranker-v2-m3"},
            "bge_base": {"enable": True, "model_name": "BAAI/bge-reranker-base"},
        },
    })

    with pytest.raises(ValueError, match="rerank must enable at most one component"):
        load_inference_config(path)


def test_load_inference_config_rejects_old_local_provider_name(tmp_path):
    from services.inference.app.config import load_inference_config

    path = tmp_path / "inference.yaml"
    path.write_text(yaml.safe_dump({
        "local": {
            "enable": True,
            "dense": {"bge_m3": {"enable": True, "model_name": "BAAI/bge-m3"}},
        },
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported inference provider: local"):
        load_inference_config(path)
