import pytest


pytestmark = pytest.mark.unit


def test_sparse_search_does_not_fill_when_query_terms_do_not_match_documents():
    from rag.sparse.bm25 import BM25Sparse

    application = BM25Sparse()
    application.start()
    documents = [
        {"id": "doc-1", "content": "人工智能 通用知识", "metadata": {}},
        {"id": "doc-2", "content": "设备巡检 操作流程", "metadata": {}},
    ]

    results = application.search("不存在词abcxyz", documents, limit=20)

    assert results == []


def test_sparse_search_returns_only_documents_with_actual_token_overlap():
    from rag.sparse.bm25 import BM25Sparse

    application = BM25Sparse()
    application.start()
    documents = [
        {"id": "doc-1", "content": "华为卡 适配流程", "metadata": {}},
        {"id": "doc-2", "content": "人工智能 通用知识", "metadata": {}},
    ]

    results = application.search("华为卡", documents, limit=20)

    assert [item["id"] for item in results] == ["doc-1"]


def test_sparse_search_does_not_match_only_single_chinese_character_tokens():
    from rag.sparse.bm25 import BM25Sparse

    application = BM25Sparse()
    application.start()
    documents = [
        {"id": "doc-1", "content": "华为卡 适配流程", "metadata": {}},
        {"id": "doc-2", "content": "买卡 越多越好", "metadata": {}},
    ]

    results = application.search("华为卡", documents, limit=20)

    assert [item["id"] for item in results] == ["doc-1"]


def test_sparse_search_uses_jieba_terms_without_phrase_requirement():
    from rag.sparse.bm25 import BM25Sparse

    application = BM25Sparse()
    application.start()
    documents = [
        {"id": "doc-1", "content": "华为卡 适配流程", "metadata": {}},
        {"id": "doc-2", "content": "华为公司 人工智能", "metadata": {}},
        {"id": "doc-3", "content": "买卡 越多越好", "metadata": {}},
    ]

    results = application.search("华为卡", documents, limit=20)

    assert [item["id"] for item in results] == ["doc-1", "doc-2"]


def test_sparse_search_uses_injected_tokenizer():
    from rag.sparse.bm25 import BM25Sparse

    class FakeTokenizer:
        def __init__(self):
            self.started = False
            self.calls = []

        def start(self):
            self.started = True

        def tokenize(self, text):
            self.calls.append(text)
            return text.lower().split()

    tokenizer = FakeTokenizer()
    application = BM25Sparse(tokenizer=tokenizer)
    application.start()
    documents = [
        {"id": "doc-1", "content": "alpha beta", "metadata": {}},
        {"id": "doc-2", "content": "gamma delta", "metadata": {}},
    ]

    results = application.search("alpha", documents, limit=20)

    assert tokenizer.started is True
    assert "alpha" in tokenizer.calls
    assert [item["id"] for item in results] == ["doc-1"]
