import pytest


pytestmark = pytest.mark.unit


def test_bge_m3_lexical_encoder_normalizes_official_weights(monkeypatch):
    from sparse.bge_m3_common import BGEM3LexicalEncoder

    class FakeModel:
        def encode(self, texts, return_dense, return_sparse, return_colbert_vecs):
            assert texts == ["query"]
            assert return_dense is False
            assert return_sparse is True
            assert return_colbert_vecs is False
            return {"lexical_weights": [{"10": 0.5, 20: 0.0, 30: 0.25}]}

    encoder = BGEM3LexicalEncoder("/models/bge-m3")
    monkeypatch.setattr(encoder, "_load_model", lambda: FakeModel())
    encoder.start()

    assert encoder.embed_documents(["query"]) == [{10: 0.5, 30: 0.25}]


def test_bge_m3_lexical_encoder_embeds_documents_in_batches():
    from sparse.bge_m3_common import BGEM3LexicalEncoder

    calls = []

    class FakeModel:
        def encode(self, texts, return_dense, return_sparse, return_colbert_vecs):
            calls.append(list(texts))
            assert return_dense is False
            assert return_sparse is True
            assert return_colbert_vecs is False
            return {"lexical_weights": [{str(index): 1.0} for index, _ in enumerate(texts)]}

    encoder = BGEM3LexicalEncoder("/models/bge-m3", batch_size=2)
    encoder._model = FakeModel()
    encoder.ready = True

    assert encoder.embed_documents(["a", "b", "c", "d", "e"]) == [{0: 1.0}, {1: 1.0}, {0: 1.0}, {1: 1.0}, {0: 1.0}]
    assert calls == [["a", "b"], ["c", "d"], ["e"]]


def test_bge_m3_sparse_converts_official_lexical_weights_to_sparse_vector(monkeypatch):
    from sparse.qdrant_bge_m3 import QdrantBGEM3Sparse

    class FakeModel:
        def encode(self, texts, return_dense, return_sparse, return_colbert_vecs):
            assert return_dense is False
            assert return_sparse is True
            assert return_colbert_vecs is False
            return {"lexical_weights": [{10: 0.5, 20: 0.25} for _ in texts]}

    sparse = QdrantBGEM3Sparse("/models/bge-m3")
    monkeypatch.setattr(sparse._encoder, "_load_model", lambda: FakeModel())
    sparse.start()

    result = sparse.embed_query("query")

    assert result.indices == [10, 20]
    assert result.values == [0.5, 0.25]
