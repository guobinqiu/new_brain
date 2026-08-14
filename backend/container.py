from __future__ import annotations

from importlib import import_module

from dependency_injector import containers, errors, providers

from dense.base import Dense
from dense.huggingface import HuggingFaceDense
from ocr.base import OCR
from ocr.paddle import PaddleOCR
from ocr.rapid import RapidOCR
from ocr.tesseract import TesseractOCR
from rerank.base import Rerank
from rerank.cross_encoder import CrossEncoderRerank
from schema import AppConfig
from search.base import Search
from search.pipeline import SearchPipeline
from sparse.base import Sparse
from sparse.bm25 import BM25Sparse
from sparse.milvus_bge_m3 import MilvusBGEM3Sparse
from sparse.milvus_bm25 import MilvusBM25Sparse
from sparse.qdrant_bge_m3 import QdrantBGEM3Sparse
from store.base import Store
from store.chroma import ChromaStore
from store.milvus import MilvusStore
from store.qdrant import QdrantStore
from tokenizer.jieba_tokenizer import JiebaTokenizer


def _component_key(name: str) -> str:
    return name.rsplit("/", 1)[-1]


def _store_key(name: str) -> str:
    key = _component_key(name)
    if key == "milvus_lite":
        return "milvus"
    return key


def _sparse_key(app_config: AppConfig) -> str:
    return _sparse_backend_key(app_config, app_config.sparse.app)


def _sparse_backend_key(app_config: AppConfig, sparse_config) -> str:
    if sparse_config is None:
        return "none"
    sparse_key = _component_key(sparse_config.name)
    if sparse_key != "bge_m3":
        return sparse_key
    store_key = _store_key(app_config.store.type)
    if store_key == "qdrant":
        return "qdrant_bge_m3"
    if store_key == "milvus":
        return "milvus_bge_m3"
    return sparse_key


class ApplicationContainer(containers.DeclarativeContainer):
    config = providers.Dependency(instance_of=AppConfig)

    dense_name = providers.Callable(lambda app_config: _component_key(app_config.dense.name), config)
    dense_model_path = providers.Callable(lambda app_config: app_config.dense.model_path, config)
    app_sparse_name = providers.Callable(lambda app_config: _component_key(app_config.sparse.app.name), config)
    app_sparse_key = providers.Callable(_sparse_key, config)
    app_sparse_tokenizer = providers.Callable(lambda app_config: app_config.sparse.app.tokenizer, config)
    app_sparse_model_path = providers.Callable(lambda app_config: app_config.sparse.app.model_path, config)
    vector_sparse_key = providers.Callable(lambda app_config: _sparse_backend_key(app_config, app_config.sparse.vector), config)
    vector_sparse_model_path = providers.Callable(lambda app_config: app_config.sparse.vector.model_path if app_config.sparse.vector is not None else None, config)
    rerank_name = providers.Callable(lambda app_config: _component_key(app_config.rerank.name), config)
    rerank_model_path = providers.Callable(lambda app_config: app_config.rerank.model_path, config)
    ocr_name = providers.Callable(lambda app_config: _component_key(app_config.ocr.name), config)
    ocr_model_path = providers.Callable(lambda app_config: app_config.ocr.model_path, config)

    qdrant_url = providers.Callable(lambda app_config: app_config.store.url, config)
    store_type = providers.Callable(lambda app_config: _store_key(app_config.store.type), config)
    chroma_persist_dir = providers.Callable(lambda app_config: app_config.store.persist_dir, config)
    milvus_uri = providers.Callable(lambda app_config: app_config.store.uri, config)
    store_timeout = providers.Callable(lambda app_config: app_config.store.timeout, config)
    chunks_collection = providers.Callable(lambda app_config: app_config.store.collections.chunks, config)

    tokenizer = providers.Selector(
        app_sparse_tokenizer,
        jieba=providers.Factory(JiebaTokenizer),
    )

    dense = providers.Selector(
        dense_name,
        test_dense=providers.Singleton(HuggingFaceDense, model_name=dense_model_path),
        huggingface=providers.Singleton(HuggingFaceDense, model_name=dense_model_path),
        bge_base=providers.Singleton(HuggingFaceDense, model_name=dense_model_path),
        bge_base_zh_v15=providers.Singleton(HuggingFaceDense, model_name=dense_model_path),
        bge_m3=providers.Singleton(HuggingFaceDense, model_name=dense_model_path),
    )

    app_sparse = providers.Selector(
        app_sparse_key,
        bm25=providers.Singleton(BM25Sparse, tokenizer=tokenizer),
        milvus_bm25=providers.Singleton(MilvusBM25Sparse),
        qdrant_bge_m3=providers.Singleton(QdrantBGEM3Sparse, model_name=app_sparse_model_path),
        milvus_bge_m3=providers.Singleton(MilvusBGEM3Sparse, model_name=app_sparse_model_path),
    )
    sparse = app_sparse

    vector_sparse = providers.Selector(
        vector_sparse_key,
        none=providers.Object(None),
        milvus_bm25=providers.Singleton(MilvusBM25Sparse),
        qdrant_bge_m3=providers.Singleton(QdrantBGEM3Sparse, model_name=vector_sparse_model_path),
        milvus_bge_m3=providers.Singleton(MilvusBGEM3Sparse, model_name=vector_sparse_model_path),
    )

    rerank = providers.Selector(
        rerank_name,
        test_rerank=providers.Singleton(CrossEncoderRerank, model_name=rerank_model_path),
        cross_encoder=providers.Singleton(CrossEncoderRerank, model_name=rerank_model_path),
        bge_base=providers.Singleton(CrossEncoderRerank, model_name=rerank_model_path),
        bge_large=providers.Singleton(CrossEncoderRerank, model_name=rerank_model_path),
        bge_m3=providers.Singleton(CrossEncoderRerank, model_name=rerank_model_path),
        bge_reranker_base=providers.Singleton(CrossEncoderRerank, model_name=rerank_model_path),
        bge_reranker_large=providers.Singleton(CrossEncoderRerank, model_name=rerank_model_path),
        bge_reranker_v2_m3=providers.Singleton(CrossEncoderRerank, model_name=rerank_model_path),
    )

    ocr = providers.Selector(
        ocr_name,
        test_ocr=providers.Singleton(RapidOCR, model_dir=ocr_model_path),
        rapid=providers.Singleton(RapidOCR, model_dir=ocr_model_path),
        rapidocr=providers.Singleton(RapidOCR, model_dir=ocr_model_path),
        paddle=providers.Singleton(PaddleOCR, model_dir=ocr_model_path),
        paddleocr=providers.Singleton(PaddleOCR, model_dir=ocr_model_path),
        tesseract=providers.Singleton(TesseractOCR, model_dir=ocr_model_path),
    )

    store = providers.Selector(
        store_type,
        qdrant=providers.Singleton(
            QdrantStore,
            dense=dense,
            sparse=vector_sparse,
            url=qdrant_url,
            timeout=store_timeout,
            chunks_collection=chunks_collection,
        ),
        chroma=providers.Singleton(
            ChromaStore,
            dense=dense,
            sparse=vector_sparse,
            persist_dir=chroma_persist_dir,
            chunks_collection=chunks_collection,
        ),
        milvus=providers.Singleton(
            MilvusStore,
            dense=dense,
            sparse=vector_sparse,
            uri=milvus_uri,
            timeout=store_timeout,
            chunks_collection=chunks_collection,
        ),
    )

    search = providers.Singleton(SearchPipeline, store=store, app_sparse=app_sparse, vector_sparse=vector_sparse)


def create_container(config: AppConfig) -> ApplicationContainer:
    container = ApplicationContainer()
    container.config.override(config)
    return container


def _resolve(provider, component_name: str, selected_name: str):
    try:
        return provider()
    except errors.Error as exc:
        raise ValueError(f"unsupported {component_name}: {selected_name}") from exc


def _load_class(import_path: str):
    module_name, class_name = import_path.rsplit(".", 1)
    return getattr(import_module(module_name), class_name)


def build_dense(config: AppConfig) -> Dense:
    if config.dense.import_path:
        return _load_class(config.dense.import_path)(model_name=config.dense.model_path)
    return _resolve(create_container(config).dense, "dense", config.dense.name)


def build_sparse(config: AppConfig) -> Sparse:
    return build_app_sparse(config)


def build_app_sparse(config: AppConfig) -> Sparse:
    sparse_config = config.sparse.app
    if sparse_config.import_path:
        cls = _load_class(sparse_config.import_path)
        key = _component_key(sparse_config.name)
        if key == "bm25":
            if sparse_config.tokenizer != "jieba":
                raise ValueError(f"unsupported sparse.tokenizer: {sparse_config.tokenizer}")
            return cls(tokenizer=JiebaTokenizer())
        if key == "milvus_bm25":
            return cls()
        return cls(model_name=sparse_config.model_path)
    return _resolve(create_container(config).app_sparse, "sparse", sparse_config.name)


def build_vector_sparse(config: AppConfig) -> Sparse | None:
    sparse_config = config.sparse.vector
    if sparse_config is None:
        return None
    if sparse_config.import_path:
        cls = _load_class(sparse_config.import_path)
        key = _component_key(sparse_config.name)
        if key == "milvus_bm25":
            return cls()
        return cls(model_name=sparse_config.model_path)
    return _resolve(create_container(config).vector_sparse, "sparse.vector", sparse_config.name)


def build_store(config: AppConfig, dense: Dense, sparse: Sparse | None = None) -> Store:
    if config.store.import_path:
        cls = _load_class(config.store.import_path)
        kwargs = {
            "dense": dense,
            "sparse": sparse,
            "chunks_collection": config.store.collections.chunks,
        }
        if _store_key(config.store.type) == "qdrant":
            kwargs["url"] = config.store.url
            kwargs["timeout"] = config.store.timeout
        elif _store_key(config.store.type) == "chroma":
            kwargs["persist_dir"] = config.store.persist_dir
        elif _store_key(config.store.type) == "milvus":
            kwargs["uri"] = config.store.uri
            kwargs["timeout"] = config.store.timeout
        return cls(**kwargs)
    container = create_container(config)
    return container.store(dense=dense, sparse=sparse)


def build_search(config: AppConfig, store: Store, sparse: Sparse) -> Search:
    return create_container(config).search(store=store, app_sparse=sparse)


def build_rerank(config: AppConfig) -> Rerank | None:
    if config.rerank is None:
        return None
    if config.rerank.import_path:
        return _load_class(config.rerank.import_path)(model_name=config.rerank.model_path)
    return _resolve(create_container(config).rerank, "rerank", config.rerank.name)


def build_ocr(config: AppConfig) -> OCR:
    if config.ocr.import_path:
        return _load_class(config.ocr.import_path)(model_dir=config.ocr.model_path)
    return _resolve(create_container(config).ocr, "ocr", config.ocr.name)
