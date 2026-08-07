from __future__ import annotations

import jieba


class JiebaTokenizer:
    def start(self) -> None:
        jieba.initialize()

    def tokenize(self, text: str) -> list[str]:
        normalized = text.lower()
        return [token.strip() for token in jieba.cut_for_search(normalized) if token.strip()]
