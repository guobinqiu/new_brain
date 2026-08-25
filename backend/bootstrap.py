from __future__ import annotations

from container import create_container
from database.base import Database
from dense.base import Dense
from loader import load_app_config
from parser.base import Parser
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
        files=None,
        store: Store | None = None,
        search: Search | None = None,
        rerank: Rerank | None = None,
        ocr: OCR | None = None,
        parser: Parser | None = None,
        database: Database | None = None,
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
        self.parser = parser or self.container.parser(ocr=self.ocr)
        self.database = database or self.container.database()
        self.search_trace = None
        self.component_errors: dict[str, str] = {}
        self.models_loaded = False
        self.ready = False

    def start(self):
        self.load_models()
        self.init_connections()

    def load_models(self):
        self._start_component("dense", self.dense)
        self._start_component("sparse", self.sparse)
        if self.rerank is not None:
            self._start_component("rerank", self.rerank)
        self._start_component("ocr", self.ocr)
        self._start_component("parser", self.parser)
        self.models_loaded = True

    def init_connections(self):
        self._start_component("store", self.store)
        self._start_component("search", self.search)
        self._start_component("database", self.database)
        self.ready = True

    def _start_component(self, name: str, component):
        self.component_errors.pop(name, None)
        try:
            component.start()
        except Exception as exc:
            self.component_errors[name] = str(exc)
            raise

    def stop(self):
        self.parser.stop()
        self.ocr.stop()
        if self.rerank is not None:
            self.rerank.stop()
        self.search.stop()
        self.store.stop()
        self.database.stop()
        self.sparse.stop()
        self.dense.stop()
        self.models_loaded = False
        self.ready = False
