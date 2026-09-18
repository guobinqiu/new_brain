import yaml
import pytest

from services.inference.app.config import load_inference_config


pytestmark = pytest.mark.unit


def test_cloud_config_does_not_require_local_models(tmp_path, monkeypatch):
    monkeypatch.setenv("SILICONFLOW_CN_API_KEY", "test-key")
    monkeypatch.setenv("SILICONFLOW_TIMEOUT", "1")
    path = tmp_path / "inference.yaml"
    path.write_text(yaml.safe_dump({"embedded": {"enable": False}, "siliconflow-cn": {
        "enable": True,
        "base_url": "https://api.siliconflow.cn/v1",
        "retry": {"max_attempts": 3, "interval_seconds": 0.5},
        "dense": {"qwen": {
            "enable": True, "model_name": "Qwen/Qwen3-Embedding-0.6B", "dimensions": 768, "timeout": 75,
        }},
        "rerank": {"bge_m3": {"enable": False, "model_name": "BAAI/bge-reranker-v2-m3", "timeout": 35}},
    }}))
    config = load_inference_config(path)
    assert config.dense is None and config.sparse is None and config.rerank is None
    assert config.siliconflow.dense_timeout == 75
    assert config.siliconflow.rerank_timeout is None
    assert config.siliconflow.retry.max_attempts == 3
    assert config.siliconflow.retry.interval_seconds == 0.5
    assert config.siliconflow.base_url == "https://api.siliconflow.cn/v1"
    assert config.siliconflow.dimensions == 768
    assert config.siliconflow.api_key == "test-key"
    assert config.siliconflow.rerank_model is None


@pytest.mark.parametrize(("provider", "base_url"), [
    ("siliconflow-cn", "https://api.siliconflow.cn/v1"),
    ("siliconflow-intl", "https://api.siliconflow.com/v1"),
])
def test_siliconflow_named_variants_share_same_provider(tmp_path, monkeypatch, provider, base_url):
    monkeypatch.setenv("SILICONFLOW_CN_API_KEY", "cn-test-key")
    monkeypatch.setenv("SILICONFLOW_INTL_API_KEY", "intl-test-key")
    path = tmp_path / "inference.yaml"
    path.write_text(yaml.safe_dump({
        "siliconflow-cn": {"enable": False, "base_url": "https://api.siliconflow.cn/v1"},
        "siliconflow-intl": {
            "enable": False,
            "base_url": "https://api.siliconflow.com/v1",
            "retry": {"max_attempts": 3, "interval_seconds": 0.5},
            "dense": {"qwen": {
                "enable": True, "model_name": "Qwen/Qwen3-Embedding-0.6B", "timeout": 30,
            }},
            "rerank": {"qwen": {
                "enable": True, "model_name": "Qwen/Qwen3-Reranker-0.6B", "timeout": 30,
            }},
        },
    } | {provider: {
        "enable": True,
        "base_url": base_url,
        "retry": {"max_attempts": 3, "interval_seconds": 0.5},
        "dense": {"qwen": {
            "enable": True, "model_name": "Qwen/Qwen3-Embedding-0.6B", "timeout": 30,
        }},
        "rerank": {"qwen": {
            "enable": True, "model_name": "Qwen/Qwen3-Reranker-0.6B", "timeout": 30,
        }},
    }}))

    config = load_inference_config(path)

    assert config.siliconflow is not None
    assert config.siliconflow.base_url == base_url
    assert config.siliconflow.api_key == ("cn-test-key" if provider == "siliconflow-cn" else "intl-test-key")
    assert config.siliconflow.dense_model == "Qwen/Qwen3-Embedding-0.6B"
    assert config.siliconflow.rerank_model == "Qwen/Qwen3-Reranker-0.6B"


def test_volcengine_config_uses_separate_embedding_and_rerank_credentials(tmp_path, monkeypatch):
    for key, value in {
        "ARK_API_KEY": "ark-test-key",
        "ARK_EMBEDDING_TIMEOUT": "1",
        "VIKING_ACCESS_KEY": "test-ak",
        "VIKING_SECRET_KEY": "test-sk",
        "VIKING_RERANK_TIMEOUT": "1",
    }.items():
        monkeypatch.setenv(key, value)
    path = tmp_path / "inference.yaml"
    path.write_text(yaml.safe_dump({"volcengine": {
        "enable": True,
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "rerank_base_url": "https://api-knowledgebase.mlp.cn-beijing.volces.com",
        "region": "cn-beijing",
        "retry": {"max_attempts": 3, "interval_seconds": 0.5},
        "dense": {"doubao_embedding_vision": {
            "enable": True, "model_name": "doubao-embedding-vision-251215", "dimensions": 1024, "timeout": 45,
        }},
        "rerank": {
            "m3_v2_rerank": {"enable": True, "model_name": "m3-v2-rerank", "timeout": 55},
            "base_multilingual_rerank": {"enable": False, "model_name": "base-multilingual-rerank"},
        },
    }}))
    config = load_inference_config(path)
    assert config.dense is None and config.sparse is None and config.siliconflow is None
    assert config.volcengine.base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert config.volcengine.rerank_base_url == "https://api-knowledgebase.mlp.cn-beijing.volces.com"
    assert config.volcengine.dense_model == "doubao-embedding-vision-251215"
    assert config.volcengine.dimensions == 1024
    assert config.volcengine.rerank_model == "m3-v2-rerank"
    assert config.volcengine.api_key == "ark-test-key"
    assert config.volcengine.dense_timeout == 45
    assert config.volcengine.sparse_timeout is None
    assert config.volcengine.rerank_timeout == 55
    assert config.volcengine.retry.max_attempts == 3
    assert config.volcengine.retry.interval_seconds == 0.5
    assert config.volcengine.access_key == "test-ak"
    assert config.volcengine.secret_key == "test-sk"
    assert config.volcengine.region == "cn-beijing"


def test_volcengine_without_rerank_does_not_require_viking_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "ark-test-key")
    for key in ("VIKING_ACCESS_KEY", "VIKING_SECRET_KEY"):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / "inference.yaml"
    path.write_text(yaml.safe_dump({"volcengine": {
        "enable": True,
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "dense": {"doubao_embedding_vision": {
            "enable": True, "model_name": "doubao-embedding-vision-251215",
        }},
        "rerank": {"base_multilingual_rerank": {"enable": False, "model_name": "base-multilingual-rerank"}},
    }}))
    assert load_inference_config(path).volcengine.rerank_model is None
    assert load_inference_config(path).volcengine.dimensions == 2048


@pytest.mark.parametrize("provider,model", [
    ("siliconflow-cn", "BAAI/bge-reranker-v2-m3"),
    ("volcengine", "base-multilingual-rerank"),
])
@pytest.mark.parametrize("enabled", [True, False])
def test_cloud_rerank_enable_controls_loaded_client(tmp_path, monkeypatch, provider, model, enabled):
    from services.inference.app import main
    from types import SimpleNamespace

    for key, value in {
        "SILICONFLOW_CN_API_KEY": "test-cn",
        "SILICONFLOW_INTL_API_KEY": "test-intl",
        "ARK_API_KEY": "test",
        "VIKING_ACCESS_KEY": "test-ak", "VIKING_SECRET_KEY": "test-sk",
    }.items():
        monkeypatch.setenv(key, value)
    path = tmp_path / "inference.yaml"
    path.write_text(yaml.safe_dump({provider: {
        "enable": True,
        "base_url": f"https://{provider}.example",
        "rerank_base_url": "https://viking.example",
        "region": "cn-beijing",
        "dense": {"dense_model": {"enable": True, "model_name": "dense"}},
        "rerank": {"rerank_model": {"enable": enabled, "model_name": model}},
    }}))
    config = load_inference_config(path)
    monkeypatch.setattr("services.inference.app.config.load_inference_config", lambda: config)
    state = SimpleNamespace()
    monkeypatch.setattr(main.app, "state", state)
    main._load_components()
    try:
        assert state.dense.model == "dense"
        assert (state.rerank is not None) is enabled
        if enabled:
            assert state.rerank.model == model
    finally:
        main._stop_components()


@pytest.mark.parametrize("enabled", [True, False])
def test_volcengine_sparse_config_controls_readiness(tmp_path, monkeypatch, enabled):
    from services.inference.app import main
    from types import SimpleNamespace

    monkeypatch.setenv("ARK_API_KEY", "test")
    path = tmp_path / "inference.yaml"
    path.write_text(yaml.safe_dump({"volcengine": {
        "enable": True,
        "base_url": "https://ark.example/api/v3",
        "dense": {"vision": {"enable": True, "model_name": "dense", "dimensions": 1024}},
        "sparse": {"vision": {"enable": enabled, "model_name": "doubao-embedding-vision-251215"}},
    }}))
    config = load_inference_config(path)
    assert config.volcengine.sparse_model == ("doubao-embedding-vision-251215" if enabled else None)
    monkeypatch.setattr("services.inference.app.config.load_inference_config", lambda: config)
    monkeypatch.setattr(main.app, "state", SimpleNamespace())
    main._load_components()
    try:
        assert main.ready()["capabilities"]["sparse"] is enabled
        assert (main.app.state.sparse is not None) is enabled
    finally:
        main._stop_components()


def test_startup_wires_volcengine_without_loading_local_models(monkeypatch):
    from services.inference.app import main
    from services.inference.app.config import InferenceConfig, VolcengineConfig

    remote = VolcengineConfig(base_url="https://ark.example/api/v3", api_key="key", dense_model="model")
    monkeypatch.setattr("services.inference.app.config.load_inference_config", lambda: InferenceConfig(
        dense=None, sparse=None, rerank=None, volcengine=remote,
    ))
    from types import SimpleNamespace
    state = SimpleNamespace()
    monkeypatch.setattr(main.app, "state", state)
    main._load_components()
    try:
        assert state.dense.model == "model"
        assert state.dense.ready
        assert state.sparse is None and state.rerank is None
    finally:
        main._stop_components()
