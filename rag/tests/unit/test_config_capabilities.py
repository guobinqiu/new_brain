from rag.api.runtime import runtime
from rag.api.services import config as service


def test_capabilities_report_store_and_sparse_support(monkeypatch):
    class Store:
        def supports_dense_vector(self):
            return True

        def supports_sparse_vector(self, sparse=None):
            return True

    class Sparse:
        def supports_sparse_vector(self):
            return True

        def supports_search_index(self):
            return False

    monkeypatch.setattr(runtime.application, "store", Store())
    monkeypatch.setattr(runtime.application, "sparse", Sparse())

    assert service.capabilities() == {
        "dense_vector": True,
        "sparse_vector": True,
        "search_index": False,
    }


def test_capabilities_report_search_index_without_sparse_vector(monkeypatch):
    class Store:
        def supports_dense_vector(self):
            return True

        def supports_sparse_vector(self, sparse=None):
            return False

    class Sparse:
        def supports_sparse_vector(self):
            return False

        def supports_search_index(self):
            return True

    monkeypatch.setattr(runtime.application, "store", Store())
    monkeypatch.setattr(runtime.application, "sparse", Sparse())

    assert service.capabilities() == {
        "dense_vector": True,
        "sparse_vector": False,
        "search_index": True,
    }
