from __future__ import annotations


class MilvusBM25Sparse:
    def __init__(self):
        self.ready = False

    def start(self) -> None:
        self.ready = True

    def stop(self) -> None:
        self.ready = False

    def search(self, query: str, documents: list[dict], limit: int) -> list[dict]:
        raise RuntimeError("Milvus BM25 uses store search")

    def as_milvus_builtin_function(self):
        from langchain_milvus import BM25BuiltInFunction

        return BM25BuiltInFunction(
            analyzer_params={"tokenizer": "jieba"},
            output_field_names="sparse",
            enable_match=True,
        )
