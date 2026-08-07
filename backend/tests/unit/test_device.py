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
