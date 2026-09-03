import pytest


pytestmark = pytest.mark.unit


def test_close_store_closes_qdrant_client_and_clears_store_cache():
    from rag.store.qdrant import QdrantStore

    class FakeClient:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    fake = FakeClient()
    store = QdrantStore()
    store.client = fake
    store._ready = True

    store.stop()

    assert fake.closed is True
    assert store.client is None
    assert store.ready is False
