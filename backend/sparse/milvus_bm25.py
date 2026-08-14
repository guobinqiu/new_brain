from __future__ import annotations


class MilvusBM25Sparse:
    analyzer_params = {"tokenizer": "jieba"}

    def __init__(self):
        self.ready = False

    def start(self) -> None:
        self.ready = True

    def stop(self) -> None:
        self.ready = False

    def search(self, query: str, documents: list[dict], limit: int) -> list[dict]:
        raise RuntimeError("Milvus BM25 uses store search")
