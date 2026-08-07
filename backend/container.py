from __future__ import annotations

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
from sparse.chroma_bge_m3 import ChromaBGEM3Sparse
from sparse.milvus_bge_m3 import MilvusBGEM3Sparse
from sparse.milvus_bm25 import MilvusBM25Sparse
from sparse.qdrant_bge_m3 import QdrantBGEM3Sparse
from store.base import Store
from store.chroma import ChromaStore
from store.milvus import MilvusStore
from store.qdrant import QdrantStore
from tokenizer.jieba_tokenizer import JiebaTokenizer


class ApplicationContainer(containers.DeclarativeContainer):
    config = providers.Dependency(instance_of=AppConfig)

    dense_name = providers.Callable(lambda app_config: _component_key(app_config.dense.name), config)
    dense_model_path = providers.Callable(lambda app_config: app_config.dense.model_path, config)
    sparse_name = providers.Callable(lambda app_config: _component_key(app_config.sparse.name), config)
    sparse_key = providers.Callable(lambda app_config: _component_key(app_config.sparse.name), config)
    sparse_tokenizer = providers.Callable(lambda app_config: app_config.sparse.tokenizer, config)
    sparse_model_path = providers.Callable(lambda app_config: app_config.sparse.model_path, config)
    rerank_name = providers.Callable(lambda app_config: _component_key(app_config.rerank.name), config)
    rerank_model_path = providers.Callable(lambda app_config: app_config.rerank.model_path, config)
    ocr_name = providers.Callable(lambda app_config: _component_key(app_config.ocr.name), config)
    ocr_model_path = providers.Callable(lambda app_config: app_config.ocr.model_path, config)

    qdrant_url = providers.Callable(lambda app_config: app_config.store.url, config)
    store_type = providers.Callable(lambda app_config: _component_key(app_config.store.type), config)
    chroma_persist_dir = providers.Callable(lambda app_config: app_config.store.persist_dir, config)
    milvus_uri = providers.Callable(lambda app_config: app_config.store.uri, config)
    common_collection = providers.Callable(lambda app_config: app_config.store.collections.common, config)
    scoped_collection = providers.Callable(lambda app_config: app_config.store.collections.scoped, config)

    tokenizer = providers.Selector(
        sparse_tokenizer,
        jieba=providers.Factory(JiebaTokenizer),
    )

    dense = providers.Selector(
        dense_name,
        test_dense=providers.Singleton(HuggingFaceDense, model_name=dense_model_path),
        huggingface=providers.Singleton(HuggingFaceDense, model_name=dense_model_path),
        bge_base_zh_v15=providers.Singleton(HuggingFaceDense, model_name=dense_model_path),
        bge_m3=providers.Singleton(HuggingFaceDense, model_name=dense_model_path),
    )

    sparse = providers.Selector(
        sparse_key,
        bm25=providers.Singleton(BM25Sparse, tokenizer=tokenizer),
        milvus_bm25=providers.Singleton(MilvusBM25Sparse),
        qdrant_bge_m3=providers.Singleton(QdrantBGEM3Sparse, model_name=sparse_model_path),
        chroma_bge_m3=providers.Singleton(ChromaBGEM3Sparse, model_name=sparse_model_path),
        milvus_bge_m3=providers.Singleton(MilvusBGEM3Sparse, model_name=sparse_model_path),
    )

    rerank = providers.Selector(
        rerank_name,
        test_rerank=providers.Singleton(CrossEncoderRerank, model_name=rerank_model_path),
        cross_encoder=providers.Singleton(CrossEncoderRerank, model_name=rerank_model_path),
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
            sparse=sparse,
            url=qdrant_url,
            common_collection=common_collection,
            scoped_collection=scoped_collection,
        ),
        chroma=providers.Singleton(
            ChromaStore,
            dense=dense,
            sparse=sparse,
            persist_dir=chroma_persist_dir,
            common_collection=common_collection,
            scoped_collection=scoped_collection,
        ),
        milvus=providers.Singleton(
            MilvusStore,
            dense=dense,
            sparse=sparse,
            uri=milvus_uri,
            common_collection=common_collection,
            scoped_collection=scoped_collection,
        ),
    )

    search = providers.Singleton(SearchPipeline, store=store, sparse=sparse)


def create_container(config: AppConfig) -> ApplicationContainer:
    container = ApplicationContainer()
    container.config.override(config)
    return container


def _component_key(name: str) -> str:
    return name.rsplit("/", 1)[-1]


def _resolve(provider, component_name: str, selected_name: str):
    try:
        return provider()
    except errors.Error as exc:
        raise ValueError(f"unsupported {component_name}: {selected_name}") from exc


def build_dense(config: AppConfig) -> Dense:
    return _resolve(create_container(config).dense, "dense", config.dense.name)


def build_sparse(config: AppConfig) -> Sparse:
    return _resolve(create_container(config).sparse, "sparse", config.sparse.name)


def build_store(config: AppConfig, dense: Dense, sparse: Sparse | None = None) -> Store:
    container = create_container(config)
    return container.store(dense=dense, sparse=sparse)


def build_search(config: AppConfig, store: Store, sparse: Sparse) -> Search:
    return create_container(config).search(store=store, sparse=sparse)


def build_rerank(config: AppConfig) -> Rerank:
    return _resolve(create_container(config).rerank, "rerank", config.rerank.name)


def build_ocr(config: AppConfig) -> OCR:
    return _resolve(create_container(config).ocr, "ocr", config.ocr.name)
