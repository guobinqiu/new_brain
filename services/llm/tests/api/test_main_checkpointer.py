import pytest


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_create_checkpointer_does_not_fallback_to_memory(monkeypatch):
    from services.llm.src import main

    class FailingSaver:
        async def __aenter__(self):
            raise RuntimeError("postgres unavailable")

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class SaverFactory:
        @staticmethod
        def from_conn_string(_url):
            return FailingSaver()

    monkeypatch.setattr(main, "AsyncPostgresSaver", SaverFactory)

    with pytest.raises(RuntimeError, match="postgres unavailable"):
        await main._create_checkpointer()
