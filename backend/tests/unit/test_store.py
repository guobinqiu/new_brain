import pytest


pytestmark = pytest.mark.unit


def test_close_store_closes_qdrant_client_and_clears_store_cache():
    import store

    class FakeClient:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    fake = FakeClient()
    store._client = fake
    store._stores[("common", "hybrid")] = object()

    store.close_store()

    assert fake.closed is True
    assert store._client is None
    assert store._stores == {}
