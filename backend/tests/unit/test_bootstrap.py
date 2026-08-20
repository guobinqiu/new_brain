import pytest


pytestmark = pytest.mark.unit


def test_application_starts_public_components_in_order():
    import bootstrap

    calls = []

    class FakeComponent:
        def __init__(self, name):
            self.name = name
            self.ready = False

        def start(self):
            calls.append(self.name)
            self.ready = True

        def stop(self):
            self.ready = False
            pass

    application = bootstrap.Application(
        dense=FakeComponent("dense"),
        sparse=FakeComponent("sparse"),
        store=FakeComponent("store"),
        search=FakeComponent("search"),
        rerank=FakeComponent("rerank"),
        ocr=FakeComponent("ocr"),
    )
    application.start()

    assert calls == ["dense", "sparse", "rerank", "ocr", "store", "search"]
    assert application.ready is True


def test_application_splits_model_loading_from_runtime_connections():
    import bootstrap

    calls = []

    class FakeComponent:
        def __init__(self, name):
            self.name = name
            self.ready = False

        def start(self):
            calls.append(self.name)
            self.ready = True

        def stop(self):
            self.ready = False

    application = bootstrap.Application(
        dense=FakeComponent("dense"),
        sparse=FakeComponent("sparse"),
        store=FakeComponent("store"),
        search=FakeComponent("search"),
        rerank=FakeComponent("rerank"),
        ocr=FakeComponent("ocr"),
    )

    application.load_models()
    application.init_connections()

    assert calls == ["dense", "sparse", "rerank", "ocr", "store", "search"]
    assert application.ready is True


def test_application_selects_production_components():
    import bootstrap
    from dense.huggingface import HuggingFaceDense
    from ocr.rapid import RapidOCR
    from search.pipeline import SearchPipeline
    from sparse.bm25 import BM25Sparse
    from store.qdrant import QdrantStore

    application = bootstrap.Application()

    assert isinstance(application.dense, HuggingFaceDense)
    assert isinstance(application.sparse, BM25Sparse)
    assert isinstance(application.store, QdrantStore)
    assert isinstance(application.search, SearchPipeline)
    assert application.rerank is None
    assert isinstance(application.ocr, RapidOCR)


def test_application_selects_configured_dense_and_bm25_sparse():
    import bootstrap
    from dense.huggingface import HuggingFaceDense
    from loader import load_config_file
    from rerank.cross_encoder import CrossEncoderRerank
    from sparse.bm25 import BM25Sparse

    config = load_config_file("config/qdrant-bge-base.yaml")
    application = bootstrap.Application(config=config)

    assert isinstance(application.dense, HuggingFaceDense)
    assert application.dense.model_name.endswith("/models/bge-base-zh-v1.5")
    assert isinstance(application.sparse, BM25Sparse)
    assert application.sparse.tokenizer.__class__.__name__ == "JiebaTokenizer"
    assert isinstance(application.rerank, CrossEncoderRerank)


def test_application_selects_bge_m3_store_sparse(tmp_path):
    import bootstrap
    from loader import load_config_file
    from sparse.qdrant_bge_m3 import QdrantBGEM3Sparse

    path = tmp_path / "qdrant_m3_sparse.yaml"
    path.write_text(
        """
database:
  type: postgres
  url: postgresql://rag:rag@localhost:5432/rag
dense:
  name: bge_m3
  model_name: bge-m3
sparse:
  type: bge_m3
  model_name: bge-m3
store:
  type: qdrant
  url: http://localhost:6333
search:
  default_mode: hybrid
rerank:
  name: bge_m3
  model_name: bge-reranker-v2-m3
ocr:
  name: rapid
  model_name: rapidocr
""",
        encoding="utf-8",
    )
    config = load_config_file(path)
    application = bootstrap.Application(config=config)

    assert isinstance(application.sparse, QdrantBGEM3Sparse)
    assert application.sparse.model_name == config.sparse.model_path
    assert application.store.sparse is application.sparse


def test_application_passes_store_config_to_qdrant_store():
    import bootstrap

    application = bootstrap.Application()

    assert application.store.url == application.config.store.url
    assert application.store.timeout == application.config.store.timeout


def test_application_reads_config_name_from_explicit_yaml(monkeypatch):
    import bootstrap

    monkeypatch.setenv("CONFIG_FILE", "qdrant-bge-base.yaml")

    application = bootstrap.Application()

    assert application.config_name == "qdrant-bge-base"
    assert application.config.dense.name == "bge_base"


def test_build_dense_rejects_unsupported_dense_type():
    import container
    from schema import AdminAuthConfig, AppConfig, AuthConfig, DatabaseConfig, DenseConfig, OCRConfig, RerankConfig, SearchConfig, SparseConfig, StoreConfig

    config = AppConfig(
        dense=DenseConfig(name="unknown", model_path="/models/dense"),
        sparse=SparseConfig(name="bm25", tokenizer="jieba"),
        store=StoreConfig(type="qdrant", url="http://localhost:6333"),
        database=DatabaseConfig(type="postgres", url="postgresql://rag:rag@localhost:5432/rag"),
        search=SearchConfig(),
        rerank=RerankConfig(name="bge_reranker_base", model_path="/models/rerank"),
        ocr=OCRConfig(name="rapidocr", model_path="/models/ocr"),
        auth=AuthConfig(
            admin=AdminAuthConfig(username="admin", password="admin123"),
        ),
    )

    with pytest.raises(ValueError, match="unsupported dense"):
        container.build_dense(config)


def test_application_does_not_become_ready_when_start_fails(monkeypatch):
    import bootstrap

    class ReadyComponent:
        def start(self):
            pass

        def stop(self):
            pass

    class FailingComponent:
        def start(self):
            raise RuntimeError("boom")

        def stop(self):
            pass

    application = bootstrap.Application(store=FailingComponent())

    with pytest.raises(RuntimeError, match="boom"):
        application.start()

    assert application.ready is False


def test_application_records_component_error_when_start_fails():
    import bootstrap

    class ReadyComponent:
        def start(self):
            pass

        def stop(self):
            pass

    class FailingComponent:
        def start(self):
            raise RuntimeError("boom")

        def stop(self):
            pass

    application = bootstrap.Application(files=ReadyComponent(), dense=FailingComponent())

    with pytest.raises(RuntimeError, match="boom"):
        application.start()

    assert application.component_errors["dense"] == "boom"


def test_application_clears_component_error_after_successful_start():
    import bootstrap

    class FakeComponent:
        def __init__(self):
            self.ready = False

        def start(self):
            self.ready = True

        def stop(self):
            self.ready = False

    application = bootstrap.Application(
        files=FakeComponent(),
        dense=FakeComponent(),
        sparse=FakeComponent(),
        store=FakeComponent(),
        search=FakeComponent(),
        ocr=FakeComponent(),
    )
    application.component_errors["dense"] = "old error"
    application.start()

    assert "dense" not in application.component_errors


def test_application_stops_public_components(monkeypatch):
    import bootstrap

    calls = []

    class FakeComponent:
        def __init__(self, name):
            self.name = name
            self.ready = True

        def start(self):
            pass

        def stop(self):
            calls.append(self.name)
            self.ready = False

    application = bootstrap.Application(
        dense=FakeComponent("dense"),
        sparse=FakeComponent("sparse"),
        store=FakeComponent("store"),
        search=FakeComponent("search"),
        rerank=FakeComponent("rerank"),
        ocr=FakeComponent("ocr"),
    )
    application.ready = True
    application.stop()

    assert calls == ["ocr", "rerank", "search", "store", "sparse", "dense"]
    assert application.ready is False
