from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.unit

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _read_config(filename: str):
    return yaml.safe_load((CONFIG_DIR / filename).read_text(encoding="utf-8"))


def test_profiles_are_store_level_not_combination_matrix():
    assert sorted(path.name for path in CONFIG_DIR.glob("*.yaml")) == [
        "chroma.yaml",
        "docker-cpu.yaml",
        "docker-gpu.yaml",
        "local.yaml",
        "milvus.yaml",
        "qdrant.yaml",
    ]


def test_profiles_select_exactly_one_component_per_group():
    for path in CONFIG_DIR.glob("*.yaml"):
        config = _read_config(path.name)

        for section_name in ("dense", "sparse", "store", "rerank", "ocr"):
            enabled = [
                name
                for name, component in config[section_name].items()
                if isinstance(component, dict) and component.get("enable") is True
            ]
            assert len(enabled) == 1, f"{path.name} {section_name} enabled={enabled}"


def test_profiles_use_explicit_import_paths_not_legacy_module_paths():
    for path in CONFIG_DIR.glob("*.yaml"):
        config = _read_config(path.name)

        for section_name in ("dense", "sparse", "store", "rerank", "ocr"):
            for component in config[section_name].values():
                assert "module" not in component
                assert "import_path" in component
                assert "." in component["import_path"]


def test_profiles_define_disabled_paddle_ocr_candidate():
    for path in CONFIG_DIR.glob("*.yaml"):
        ocr = _read_config(path.name)["ocr"]

        assert ocr["paddle"]["enable"] is False
        assert ocr["paddle"]["model_name"] == "paddleocr"


def test_profiles_define_disabled_tesseract_ocr_candidate():
    for path in CONFIG_DIR.glob("*.yaml"):
        ocr = _read_config(path.name)["ocr"]

        assert ocr["tesseract"]["enable"] is False
        assert ocr["tesseract"]["model_name"] == "tesseract"


def test_chroma_profile_does_not_include_unsupported_store_sparse_candidate():
    config = _read_config("chroma.yaml")

    assert set(config["sparse"]) == {"bm25"}


def test_profiles_define_search_result_and_candidate_limits():
    for path in CONFIG_DIR.glob("*.yaml"):
        config = _read_config(path.name)

        assert config["search"]["top_k"] == 20
        assert config["search"]["fetch_k"] == 50
        assert config["search"]["fetch_k"] >= config["search"]["top_k"]


def test_profiles_use_index_specific_collection_names():
    expected = {
        "qdrant.yaml": (
            ("qdrant",),
            "qdrant_knowledge_common",
            "qdrant_knowledge_scoped",
        ),
        "chroma.yaml": (
            ("chroma",),
            "chroma_knowledge_common",
            "chroma_knowledge_scoped",
        ),
        "milvus.yaml": (
            ("milvus", "milvus_lite"),
            "milvus_knowledge_common",
            "milvus_knowledge_scoped",
        ),
        "local.yaml": (
            ("qdrant",),
            "knowledge_common",
            "knowledge_scoped",
        ),
        "docker-cpu.yaml": (
            ("qdrant",),
            "knowledge_common",
            "knowledge_scoped",
        ),
        "docker-gpu.yaml": (
            ("qdrant",),
            "knowledge_common",
            "knowledge_scoped",
        ),
    }

    for filename, (store_names, common, scoped) in expected.items():
        stores = _read_config(filename)["store"]

        for store_name in store_names:
            assert stores[store_name]["collections"]["common"] == common
            assert stores[store_name]["collections"]["scoped"] == scoped


def test_milvus_profile_uses_uri_for_runtime_shape_not_filename():
    config = _read_config("milvus.yaml")
    store = _enabled_component(config, "store")

    assert "lite" not in "milvus.yaml"
    assert "standalone" not in "milvus.yaml"
    assert isinstance(store["uri"], str)
    assert store["uri"]


def test_milvus_profile_defines_lite_runtime_without_forcing_default_choice():
    config = _read_config("milvus.yaml")

    assert config["store"]["milvus"]["uri"] == "http://localhost:19530"
    assert config["store"]["milvus_lite"]["uri"] == "milvus_data/lite/lite.db"
    assert config["store"]["milvus_lite"]["collections"] == config["store"]["milvus"]["collections"]


def test_milvus_profile_defines_standalone_and_lite_runtimes():
    store = _read_config("milvus.yaml")["store"]

    assert set(store) == {"milvus", "milvus_lite"}
    assert store["milvus"]["collections"] == {
        "common": "milvus_knowledge_common",
        "scoped": "milvus_knowledge_scoped",
    }
    assert store["milvus_lite"]["collections"] == store["milvus"]["collections"]


def test_docker_gpu_profile_uses_benchmark_backed_retrieval_with_stronger_rerank():
    config = _read_config("docker-gpu.yaml")

    assert _enabled_component(config, "dense")["model_name"] == "bge-base-zh-v1.5"
    assert _enabled_component(config, "dense")["import_path"] == "dense.huggingface.HuggingFaceDense"
    assert _enabled_component(config, "sparse")["tokenizer"] == "jieba"
    assert _enabled_component(config, "sparse")["import_path"] == "sparse.bm25.BM25Sparse"
    assert _enabled_component(config, "rerank")["model_name"] == "bge-reranker-v2-m3"
    assert _enabled_component(config, "rerank")["import_path"] == "rerank.cross_encoder.CrossEncoderRerank"
    assert config["search"]["default_mode"] == "hybrid"


def test_docker_cpu_profile_keeps_lightweight_models_with_app_bm25_sparse():
    config = _read_config("docker-cpu.yaml")

    assert _enabled_component(config, "dense")["model_name"] == "bge-base-zh-v1.5"
    assert _enabled_component(config, "dense")["import_path"] == "dense.huggingface.HuggingFaceDense"
    assert _enabled_component(config, "sparse")["tokenizer"] == "jieba"
    assert _enabled_component(config, "sparse")["import_path"] == "sparse.bm25.BM25Sparse"
    assert _enabled_component(config, "rerank")["model_name"] == "bge-reranker-base"
    assert _enabled_component(config, "rerank")["import_path"] == "rerank.cross_encoder.CrossEncoderRerank"
    assert config["search"]["default_mode"] == "hybrid"


def _enabled_component(config: dict, section_name: str) -> dict:
    return next(component for component in config[section_name].values() if component.get("enable") is True)
