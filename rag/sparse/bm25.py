from __future__ import annotations

import re

from rank_bm25 import BM25L
from rag.tokenizer.base import Tokenizer
from rag.tokenizer.jieba_tokenizer import JiebaTokenizer


class BM25Sparse:
    def __init__(self, tokenizer: Tokenizer | None = None):
        self.tokenizer = tokenizer or JiebaTokenizer()
        self.ready = False

    def start(self) -> None:
        self.tokenizer.start()
        self.ready = True

    def stop(self) -> None:
        self.ready = False

    def search(self, query: str, documents: list[dict], limit: int) -> list[dict]:
        if not self.ready:
            raise RuntimeError("sparse is not initialized")
        if not documents:
            return []
        tokenized_documents = [self.tokenizer.tokenize(document["content"]) for document in documents]
        tokenized_query = self.tokenizer.tokenize(query)
        if not tokenized_query:
            return []
        bm25 = BM25L(tokenized_documents)
        scores = bm25.get_scores(tokenized_query)
        items = []
        for document, score in zip(documents, scores):
            if score <= 0:
                continue
            if not _has_meaningful_overlap(document["content"], tokenized_query, self.tokenizer):
                continue
            item = dict(document)
            item["_score"] = float(score)
            items.append(item)
        items.sort(key=lambda item: item["_score"], reverse=True)
        return items[:limit]


def _has_meaningful_overlap(content: str, tokenized_query: list[str], tokenizer: Tokenizer) -> bool:
    query_terms = _meaningful_terms(tokenized_query)
    if not query_terms:
        return False
    content_terms = set(_meaningful_terms(tokenizer.tokenize(content)))
    return any(term in content_terms for term in query_terms)


def _meaningful_terms(tokens: list[str]) -> list[str]:
    return [
        token
        for token in tokens
        if not re.fullmatch(r"[\W_]+", token)
        and not re.fullmatch(r"[\u4e00-\u9fff]", token)
    ]
