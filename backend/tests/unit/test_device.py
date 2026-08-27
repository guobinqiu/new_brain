import pytest


pytestmark = pytest.mark.unit


def test_selects_cuda_when_torch_reports_cuda(monkeypatch):
    import device

    class FakeCuda:
        @staticmethod
        def is_available():
            return True

    class FakeTorch:
        cuda = FakeCuda()

    monkeypatch.setattr(device, "_load_torch", lambda: FakeTorch())

    assert device.auto_device() == "cuda"


def test_falls_back_to_cpu_when_cuda_is_not_available(monkeypatch):
    import device

    class FakeCuda:
        @staticmethod
        def is_available():
            return False

    class FakeTorch:
        cuda = FakeCuda()

    monkeypatch.setattr(device, "_load_torch", lambda: FakeTorch())

    assert device.auto_device() == "cpu"


def test_falls_back_to_cpu_when_torch_cannot_be_loaded(monkeypatch):
    import device

    def fail():
        raise ImportError("torch unavailable")

    monkeypatch.setattr(device, "_load_torch", fail)

    assert device.auto_device() == "cpu"


def test_release_memory_clears_cuda_cache_when_available(monkeypatch):
    import device

    calls = []

    class FakeCuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def empty_cache():
            calls.append("empty_cache")

    class FakeTorch:
        cuda = FakeCuda()

    monkeypatch.setattr(device, "_load_torch", lambda: FakeTorch())

    device.release_memory()

    assert calls == ["empty_cache"]


def test_release_memory_ignores_missing_torch(monkeypatch):
    import device

    def fail():
        raise ImportError("torch unavailable")

    monkeypatch.setattr(device, "_load_torch", fail)

    device.release_memory()


def test_dense_passes_auto_device_to_huggingface_embeddings(monkeypatch):
    from dense.huggingface import HuggingFaceDense

    calls = {}

    class FakeEmbeddings:
        def __init__(self, **kwargs):
            calls.update(kwargs)

        def embed_query(self, text):
            return [1.0, 2.0]

    monkeypatch.setattr("device.auto_device", lambda: "cuda")
    monkeypatch.setitem(__import__("sys").modules, "langchain_huggingface", type("Module", (), {"HuggingFaceEmbeddings": FakeEmbeddings}))

    dense = HuggingFaceDense(model_name="/models/bge")
    dense.start()

    assert calls["model_name"] == "/models/bge"
    assert calls["model_kwargs"] == {"device": "cuda"}


def test_dense_stop_releases_loaded_model(monkeypatch):
    from dense.huggingface import HuggingFaceDense

    calls = []

    dense = HuggingFaceDense(model_name="/models/bge")
    dense._dense = object()
    dense._vector_size = 2
    dense.ready = True
    monkeypatch.setattr("device.release_memory", lambda: calls.append("release"))

    dense.stop()

    assert dense._dense is None
    assert dense._vector_size is None
    assert dense.ready is False
    assert calls == ["release"]


def test_dense_embeds_documents_in_batches():
    from dense.huggingface import HuggingFaceDense

    calls = []

    class FakeEmbeddings:
        def embed_documents(self, texts):
            calls.append(list(texts))
            return [[float(len(text))] for text in texts]

    dense = HuggingFaceDense(model_name="/models/bge", batch_size=2)
    dense._dense = FakeEmbeddings()
    dense._vector_size = 1
    dense.ready = True

    assert dense.embed_documents(["a", "bb", "ccc", "dddd", "eeeee"]) == [[1.0], [2.0], [3.0], [4.0], [5.0]]
    assert calls == [["a", "bb"], ["ccc", "dddd"], ["eeeee"]]


def test_rerank_passes_auto_device_to_cross_encoder(monkeypatch):
    import importlib
    import rerank.cross_encoder

    calls = {}

    class FakeCrossEncoder:
        def __init__(self, **kwargs):
            calls.update(kwargs)

    monkeypatch.setattr("device.auto_device", lambda: "cuda")
    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", type("Module", (), {"CrossEncoder": FakeCrossEncoder}))
    module = importlib.reload(rerank.cross_encoder)

    rerank = module.CrossEncoderRerank(model_name="/models/rerank")
    rerank._load_reranker()

    assert calls == {"model_name": "/models/rerank", "device": "cuda"}


def test_bge_m3_sparse_stop_releases_loaded_model(monkeypatch):
    from sparse.bge_m3_common import BGEM3LexicalEncoder

    calls = []

    sparse = BGEM3LexicalEncoder(model_name="/models/bge-m3")
    sparse._model = object()
    sparse.ready = True
    monkeypatch.setattr("device.release_memory", lambda: calls.append("release"))

    sparse.stop()

    assert sparse._model is None
    assert sparse.ready is False
    assert calls == ["release"]
