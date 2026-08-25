from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.unit

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _read_config(filename: str):
    return yaml.safe_load((CONFIG_DIR / filename).read_text(encoding="utf-8"))


def test_profiles_are_fixed_index_profiles():
    assert sorted(path.name for path in CONFIG_DIR.glob("*.yaml")) == [
        "chroma-bge-base.yaml",
        "chroma-bge-m3.yaml",
        "docker-cpu.yaml",
        "docker-gpu.yaml",
        "local.yaml",
        "milvus-bge-base.yaml",
        "milvus-bge-m3.yaml",
        "milvus-builtin-bm25.yaml",
        "milvus-lite-bge-base.yaml",
        "milvus-lite-bge-m3.yaml",
        "milvus-lite-builtin-bm25.yaml",
        "qdrant-bge-base.yaml",
        "qdrant-bge-m3.yaml",
    ]


def test_profiles_fix_index_shaping_components():
    for path in CONFIG_DIR.glob("*.yaml"):
        config = _read_config(path.name)

        assert "import_path" in config["dense"]
        assert "import_path" in config["store"]


def test_profiles_define_one_sparse_backend_from_filename():
    expected = {
        "docker-gpu.yaml": "bge_m3",
        "qdrant-bge-m3.yaml": "bge_m3",
        "milvus-bge-m3.yaml": "bge_m3",
        "milvus-builtin-bm25.yaml": "milvus_bm25",
        "milvus-lite-bge-m3.yaml": "bge_m3",
        "milvus-lite-builtin-bm25.yaml": "milvus_bm25",
    }

    for path in CONFIG_DIR.glob("*.yaml"):
        sparse = _read_config(path.name)["sparse"]

        if path.name in expected:
            assert sparse["type"] == expected[path.name]
        else:
            assert sparse["type"] == "bm25"
            assert sparse["tokenizer"] == "jieba"
        assert "import_path" in sparse


def test_profiles_select_at_most_one_rerank_component():
    for path in CONFIG_DIR.glob("*.yaml"):
        config = _read_config(path.name)

        if config["rerank"] is not None and _is_component_group(config["rerank"]):
            enabled = _enabled_components(config["rerank"])
            assert len(enabled) <= 1, f"{path.name} rerank enabled={enabled}"


def test_profiles_use_explicit_import_paths():
    for path in CONFIG_DIR.glob("*.yaml"):
        config = _read_config(path.name)

        for section_name in ("dense", "store", "ocr"):
            for component in _components(config[section_name]):
                assert "import_path" in component
                assert "." in component["import_path"]
        if config["rerank"] is not None:
            for component in _components(config["rerank"]):
                assert "import_path" in component
                assert "." in component["import_path"]
        assert "import_path" in config["sparse"]
        assert "." in config["sparse"]["import_path"]


def test_profiles_keep_runtime_ocr_candidates():
    for path in CONFIG_DIR.glob("*.yaml"):
        ocr = _read_config(path.name)["ocr"]

        assert _enabled_components(ocr)[0]["model_name"] == "rapidocr"
        assert ocr["paddle"]["enable"] is False
        assert ocr["tesseract"]["enable"] is False


def test_chroma_profile_uses_app_bm25_sparse():
    for filename in ("chroma-bge-base.yaml", "chroma-bge-m3.yaml"):
        config = _read_config(filename)

        assert config["sparse"]["type"] == "bm25"


def test_profiles_define_search_result_and_candidate_limits():
    for path in CONFIG_DIR.glob("*.yaml"):
        config = _read_config(path.name)

        assert config["search"]["top_k"] == 5
        assert config["search"]["fetch_k"] == 20
        assert config["search"]["fetch_k"] >= config["search"]["top_k"]


def test_config_files_define_parser_defaults():
    for path in CONFIG_DIR.glob("*.yaml"):
        parser = _read_config(path.name)["parser"]

        assert parser["type"] == "standard"
        assert parser["text"]["chunk_size"] == 500
        assert parser["text"]["chunk_overlap"] == 80
        assert parser["table"]["chunk_size"] == 1000
        assert parser["table"]["before_text_size"] == 160
        assert parser["table"]["after_text_size"] == 160


def test_profiles_define_store_type_from_filename():
    expected_store = {
        "qdrant-bge-base.yaml": "qdrant",
        "qdrant-bge-m3.yaml": "qdrant",
        "chroma-bge-base.yaml": "chroma",
        "chroma-bge-m3.yaml": "chroma",
        "milvus-bge-base.yaml": "milvus",
        "milvus-bge-m3.yaml": "milvus",
        "milvus-builtin-bm25.yaml": "milvus",
        "milvus-lite-bge-base.yaml": "milvus_lite",
        "milvus-lite-bge-m3.yaml": "milvus_lite",
        "milvus-lite-builtin-bm25.yaml": "milvus_lite",
        "local.yaml": "qdrant",
        "docker-cpu.yaml": "qdrant",
        "docker-gpu.yaml": "qdrant",
    }

    for filename, store_name in expected_store.items():
        store = _read_config(filename)["store"]

        assert store["type"] == store_name


def test_milvus_profiles_split_standalone_and_lite_runtime_shape():
    for filename in ("milvus-bge-base.yaml", "milvus-bge-m3.yaml", "milvus-builtin-bm25.yaml"):
        store = _read_config(filename)["store"]

        assert store["type"] == "milvus"
        assert store["uri"] == "http://localhost:19530"

    for filename in ("milvus-lite-bge-base.yaml", "milvus-lite-bge-m3.yaml", "milvus-lite-builtin-bm25.yaml"):
        store = _read_config(filename)["store"]

        assert store["type"] == "milvus_lite"
        assert store["uri"] == f"milvus_data/lite/{Path(filename).stem}.db"


def test_docker_gpu_profile_uses_benchmark_backed_retrieval_with_stronger_rerank():
    config = _read_config("docker-gpu.yaml")

    assert config["dense"]["model_name"] == "bge-m3"
    assert config["dense"]["import_path"] == "dense.huggingface.HuggingFaceDense"
    assert config["sparse"]["type"] == "bge_m3"
    assert config["sparse"]["import_path"] == "sparse.qdrant_bge_m3.QdrantBGEM3Sparse"
    rerank = _enabled_components(config["rerank"])[0]
    assert rerank["model_name"] == "bge-reranker-v2-m3"
    assert rerank["import_path"] == "rerank.cross_encoder.CrossEncoderRerank"
    assert config["search"]["default_mode"] == "hybrid"


def test_docker_cpu_profile_keeps_lightweight_models_with_app_bm25_sparse():
    config = _read_config("docker-cpu.yaml")

    assert config["dense"]["model_name"] == "bge-base-zh-v1.5"
    assert config["dense"]["import_path"] == "dense.huggingface.HuggingFaceDense"
    assert config["sparse"]["type"] == "bm25"
    assert config["sparse"]["tokenizer"] == "jieba"
    assert config["sparse"]["import_path"] == "sparse.bm25.BM25Sparse"
    assert _enabled_components(config["rerank"]) == []
    assert config["search"]["default_mode"] == "hybrid"


def test_profiles_define_database_component():
    for path in CONFIG_DIR.glob("*.yaml"):
        config = _read_config(path.name)

        assert config["database"]["type"] == "postgres"
        assert "url" in config["database"]
        assert "import_path" in config["database"]
        assert "." in config["database"]["import_path"]


def _is_component_group(section: dict) -> bool:
    if not isinstance(section, dict):
        return False
    if any(key in section for key in ("name", "type", "app", "vector")):
        return False
    return all(isinstance(value, dict) for value in section.values())


def _components(section: dict) -> list[dict]:
    if _is_component_group(section):
        return list(section.values())
    return [section]


def _enabled_components(section: dict) -> list[dict]:
    if section is None:
        return []
    if _is_component_group(section):
        return [component for component in section.values() if component.get("enable") is True]
    return [section]
