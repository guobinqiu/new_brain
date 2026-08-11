from __future__ import annotations

from container import create_container
from dense.base import Dense
from loader import load_app_config
from schema import AppConfig
from ocr.base import OCR
from rerank.base import Rerank
from search.base import Search
from sparse.base import Sparse
from store.base import Store


class Application:
    def __init__(
        self,
        config: AppConfig | None = None,
        dense: Dense | None = None,
        sparse: Sparse | None = None,
        store: Store | None = None,
        search: Search | None = None,
        rerank: Rerank | None = None,
        ocr: OCR | None = None,
    ):
        self.config = config or load_app_config()
        self.config_name = self.config.name
        self.container = create_container(self.config)
        self.dense = dense or self.container.dense()
        self.sparse = sparse or self.container.sparse()
        self.store = store or self.container.store(dense=self.dense, sparse=self.sparse)
        self.search = search or self.container.search(store=self.store, sparse=self.sparse)
        self.rerank = rerank or (self.container.rerank() if self.config.rerank is not None else None)
        self.ocr = ocr or self.container.ocr()
        self.ready = False

    def start(self):
        self.store.start()
        self.search.start()
        if self.rerank is not None:
            self.rerank.start()
        self.ocr.start()
        self.ready = True

    def stop(self):
        self.ocr.stop()
        if self.rerank is not None:
            self.rerank.stop()
        self.search.stop()
        self.store.stop()
        self.ready = False
