import pytest


pytestmark = pytest.mark.unit


class RealisticFakeReranker:
    """Mimics sentence-transformers 5.x CrossEncoder: has predict(), no score()."""

    def __init__(self):
        self.calls = []

    def predict(self, pairs, batch_size=None):
        self.calls.append((pairs, batch_size))
        return [float(len(p[1])) for p in pairs]


class ThresholdFakeReranker:
    def predict(self, pairs, batch_size=None):
        return [-0.5, 0.0, 0.8]


def _make_item(item_id: str, content: str) -> dict:
    """Build a search result dict in the shape returned by search functions."""
    return {
        "id": item_id,
        "content": content,
        "metadata": {"filename": "test_ai.txt"},
        "method": "dense",
    }


class TestRerank:
    """rerank.py – cross-encoder reranking of search results."""

    def test_rerank_requires_start_before_rerank(self):
        from rerank.cross_encoder import CrossEncoderRerank

        application = CrossEncoderRerank()

        with pytest.raises(RuntimeError, match="rerank is not initialized"):
            application.rerank("query", [_make_item("id", "content")], top_k=1)

    def test_rerank_uses_started_model(self):
        from rerank.cross_encoder import CrossEncoderRerank

        application = CrossEncoderRerank()
        application._reranker = RealisticFakeReranker()
        application.ready = True

        results = application.rerank(
            "query",
            [_make_item("short", "x"), _make_item("long", "x" * 10)],
            top_k=2,
        )

        assert [item["id"] for item in results] == ["long", "short"]

    def test_rerank_returns_topk(self):
        """``rerank`` returns exactly ``top_k`` items."""
        from rerank.cross_encoder import CrossEncoderRerank

        items = [_make_item(f"id{i}", f"content {i}" * (i + 1)) for i in range(6)]
        application = CrossEncoderRerank()
        application._reranker = RealisticFakeReranker()
        application.ready = True
        results = application.rerank("test query", items, top_k=3)
        assert len(results) == 3

    def test_rerank_preserves_dict_shape(self):
        """Reranked items keep the {id, content, metadata, method} shape."""
        from rerank.cross_encoder import CrossEncoderRerank

        items = [_make_item(f"id{i}", f"content {i}") for i in range(4)]
        application = CrossEncoderRerank()
        application._reranker = RealisticFakeReranker()
        application.ready = True
        results = application.rerank("test query", items, top_k=2)
        assert len(results) == 2
        for r in results:
            for key in ("id", "content", "metadata", "method"):
                assert key in r
            assert "score" not in r

    def test_rerank_sets_internal_score(self):
        from rerank.cross_encoder import CrossEncoderRerank

        items = [_make_item("short", "x"), _make_item("long", "x" * 10)]
        application = CrossEncoderRerank()
        application._reranker = RealisticFakeReranker()
        application.ready = True

        results = application.rerank("query", items, top_k=2)

        assert results[0]["_score"] == 10.0
        assert results[1]["_score"] == 1.0

    def test_rerank_sorts_by_score(self):
        """FakeReranker scores by content length → longest content ranks first."""
        from rerank.cross_encoder import CrossEncoderRerank

        items = [
            _make_item("short", "AGI"),
            _make_item("long", "AGI " * 20),
            _make_item("mid", "AGI " * 5),
        ]
        application = CrossEncoderRerank()
        application._reranker = RealisticFakeReranker()
        application.ready = True
        results = application.rerank("agi", items, top_k=3)
        assert [r["id"] for r in results] == ["long", "mid", "short"]

    def test_rerank_passes_batch_size_to_predict(self):
        from rerank.cross_encoder import CrossEncoderRerank

        fake = RealisticFakeReranker()
        items = [_make_item(f"id{i}", f"content {i}") for i in range(5)]
        application = CrossEncoderRerank(batch_size=2)
        application._reranker = fake
        application.ready = True

        application.rerank("test query", items, top_k=3)

        assert fake.calls == [([("test query", item["content"]) for item in items], 2)]

    def test_rerank_empty_items(self):
        """``rerank`` with no items returns an empty list."""
        from rerank.cross_encoder import CrossEncoderRerank

        application = CrossEncoderRerank()
        assert application.rerank("test query", [], top_k=3) == []

    def test_rerank_topk_larger_than_items(self):
        """``top_k`` larger than the item count returns all items."""
        from rerank.cross_encoder import CrossEncoderRerank

        items = [_make_item(f"id{i}", f"content {i}") for i in range(3)]
        application = CrossEncoderRerank()
        application._reranker = RealisticFakeReranker()
        application.ready = True
        results = application.rerank("test query", items, top_k=10)
        assert len(results) == 3

    def test_rerank_filters_negative_scores_even_when_topk_is_larger(self):
        """rerank 分小于 0 的候选不返回;top_k 只是最多返回条数。"""
        from rerank.cross_encoder import CrossEncoderRerank

        items = [
            _make_item("bad", "bad"),
            _make_item("zero", "zero"),
            _make_item("good", "good"),
        ]
        application = CrossEncoderRerank()
        application._reranker = ThresholdFakeReranker()
        application.ready = True
        results = application.rerank("query", items, top_k=10)

        assert [item["id"] for item in results] == ["good", "zero"]


class TestRerankRealAPI:
    """rerank.py – regression guard for the sentence-transformers 5.x API.

    sentence-transformers 5.6.1 renamed ``CrossEncoder.score()`` to
    ``CrossEncoder.predict()``. The old ``FakeReranker`` (score-only) could
    never catch code that calls ``.score()`` on the real 5.x API shape,
    which raised AttributeError → 500. These tests use a fake with the
    *real* API shape (predict only, no score).
    """

    def test_rerank_uses_predict_api(self, monkeypatch):
        """``rerank`` calls ``predict`` on a 5.x-style reranker (no error).

        Regression: rerank.py previously called ``.score()``, which no
        longer exists in sentence-transformers >= 5.x → AttributeError → 500.
        """
        from rerank.cross_encoder import CrossEncoderRerank

        fake = RealisticFakeReranker()

        items = [
            _make_item("short", "AGI"),
            _make_item("long", "AGI " * 20),
            _make_item("mid", "AGI " * 5),
        ]
        application = CrossEncoderRerank()
        application._reranker = fake
        application.ready = True
        results = application.rerank("agi", items, top_k=2)

        # No AttributeError raised — the regression itself
        assert len(results) == 2
        # predict() received the (query, content) pairs
        assert fake.calls == [([("agi", item["content"]) for item in items], 4)]
        # predict() scores drove the ranking (longest content first)
        assert [r["id"] for r in results] == ["long", "mid"]

    def test_rerank_fake_without_score(self):
        """Document the API contract: realistic fake has predict, no score."""
        fake = RealisticFakeReranker()

        assert hasattr(fake, "predict")
        assert not hasattr(fake, "score")
