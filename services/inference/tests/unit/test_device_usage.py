import pytest


pytestmark = pytest.mark.unit


def test_embedded_clients_are_exported_from_provider_modules():
    from services.inference.providers.embedded.dense import HuggingFaceDense
    from services.inference.providers.embedded.rerank import CrossEncoderRerank
    from services.inference.providers.embedded.sparse import BgeM3Sparse

    assert HuggingFaceDense.__name__ == "HuggingFaceDense"
    assert BgeM3Sparse.__name__ == "BgeM3Sparse"
    assert CrossEncoderRerank.__name__ == "CrossEncoderRerank"


def test_dense_passes_auto_device_to_huggingface_embeddings(monkeypatch):
    from services.inference.providers.embedded.dense import HuggingFaceDense

    calls = {}

    class FakeEmbeddings:
        def __init__(self, **kwargs):
            calls.update(kwargs)

        def embed_query(self, text):
            return [1.0, 2.0]

        def embed_documents(self, texts):
            return [[1.0, 2.0] for _ in texts]

    monkeypatch.setattr("shared.device.auto_device", lambda: "cuda")
    monkeypatch.setitem(__import__("sys").modules, "langchain_huggingface", type("Module", (), {"HuggingFaceEmbeddings": FakeEmbeddings}))

    dense = HuggingFaceDense(model_name="/models/bge")
    dense.start()

    assert calls["model_name"] == "/models/bge"
    assert calls["model_kwargs"] == {"device": "cuda"}


def test_dense_start_warms_document_embedding_path(monkeypatch):
    from services.inference.providers.embedded.dense import HuggingFaceDense

    calls = []

    class FakeEmbeddings:
        def __init__(self, **kwargs):
            pass

        def embed_query(self, text):
            calls.append(("query", text))
            return [1.0, 2.0]

        def embed_documents(self, texts):
            calls.append(("documents", list(texts)))
            return [[1.0, 2.0] for _ in texts]

    monkeypatch.setitem(__import__("sys").modules, "langchain_huggingface", type("Module", (), {"HuggingFaceEmbeddings": FakeEmbeddings}))

    dense = HuggingFaceDense(model_name="/models/bge")
    dense.start()

    assert calls == [("query", "dimension probe"), ("documents", ["warmup"])]


def test_dense_stop_releases_loaded_model(monkeypatch):
    from services.inference.providers.embedded.dense import HuggingFaceDense

    calls = []

    dense = HuggingFaceDense(model_name="/models/bge")
    dense._dense = object()
    dense._vector_size = 2
    dense.ready = True
    monkeypatch.setattr("shared.device.release_memory", lambda: calls.append("release"))

    dense.stop()

    assert dense._dense is None
    assert dense._vector_size is None
    assert dense.ready is False
    assert calls == ["release"]


def test_dense_embeds_documents_in_batches():
    from services.inference.providers.embedded.dense import HuggingFaceDense

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


def test_dense_release_memory_after_call(monkeypatch):
    from services.inference.providers.embedded.dense import HuggingFaceDense

    calls = []

    class FakeEmbeddings:
        def embed_documents(self, texts):
            return [[1.0] for _ in texts]

    dense = HuggingFaceDense(model_name="/models/bge", batch_size=2, release_memory="after_call")
    dense._dense = FakeEmbeddings()
    dense._vector_size = 1
    dense.ready = True
    monkeypatch.setattr("shared.device.release_memory", lambda: calls.append("release"))

    dense.embed_documents(["a", "b", "c", "d", "e"])

    assert calls == ["release"]


def test_dense_release_memory_per_batch(monkeypatch):
    from services.inference.providers.embedded.dense import HuggingFaceDense

    calls = []

    class FakeEmbeddings:
        def embed_documents(self, texts):
            return [[1.0] for _ in texts]

    dense = HuggingFaceDense(model_name="/models/bge", batch_size=2)
    dense._dense = FakeEmbeddings()
    dense._vector_size = 1
    dense.ready = True
    monkeypatch.setattr("shared.device.release_memory", lambda: calls.append("release"))

    dense.embed_documents(["a", "b", "c", "d", "e"])

    assert calls == ["release", "release", "release"]


def test_rerank_passes_auto_device_to_cross_encoder(monkeypatch):
    import importlib
    import services.inference.providers.embedded.rerank

    calls = {}

    class FakeCrossEncoder:
        def __init__(self, **kwargs):
            calls.update(kwargs)

    monkeypatch.setattr("shared.device.auto_device", lambda: "cuda")
    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", type("Module", (), {"CrossEncoder": FakeCrossEncoder}))
    module = importlib.reload(services.inference.providers.embedded.rerank)

    rerank = module.CrossEncoderRerank(model_name="/models/rerank")
    rerank._load_reranker()

    assert calls == {"model_name": "/models/rerank", "device": "cuda"}
