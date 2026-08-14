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
        vector_sparse: Sparse | None = None,
        files=None,
        store: Store | None = None,
        search: Search | None = None,
        rerank: Rerank | None = None,
        ocr: OCR | None = None,
    ):
        self.config = config or load_app_config()
        self.config_name = self.config.name
        self.container = create_container(self.config)
        self.dense = dense or self.container.dense()
        self.sparse = sparse or self.container.app_sparse()
        self.vector_sparse = vector_sparse if vector_sparse is not None else self.container.vector_sparse()
        self.store = store or self.container.store(dense=self.dense, sparse=self.vector_sparse)
        self.search = search or self.container.search(store=self.store, app_sparse=self.sparse, vector_sparse=self.vector_sparse)
        self.rerank = rerank or (self.container.rerank() if self.config.rerank is not None else None)
        self.ocr = ocr or self.container.ocr()
        self.search_trace = None
        self.component_errors: dict[str, str] = {}
        self.ready = False

    def start(self):
        self._start_component("dense", self.dense)
        self._start_component("sparse", self.sparse)
        if self.vector_sparse is not None:
            self._start_component("vector_sparse", self.vector_sparse)
        self._start_component("store", self.store)
        self._start_component("search", self.search)
        if self.rerank is not None:
            self._start_component("rerank", self.rerank)
        self._start_component("ocr", self.ocr)
        self.ready = True

    def _start_component(self, name: str, component):
        self.component_errors.pop(name, None)
        try:
            component.start()
        except Exception as exc:
            self.component_errors[name] = str(exc)
            raise

    def stop(self):
        self.ocr.stop()
        if self.rerank is not None:
            self.rerank.stop()
        self.search.stop()
        self.store.stop()
        if self.vector_sparse is not None:
            self.vector_sparse.stop()
        self.sparse.stop()
        self.dense.stop()
        self.ready = False
