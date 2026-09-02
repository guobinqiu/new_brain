import os
from dataclasses import asdict
from typing import Any

from rag.api.runtime import runtime
from rag.api.services.common import component_config, now_iso
from rag.config import SEARCH_CONFIG
from rag.nodes import fetch_peers, local_result, node_id, parse_peers


def get_config(_):
    return config_payload()


async def nodes_config(authorization: str | None, _):
    peers = parse_peers(os.getenv("RAG_PEERS"))
    if not peers:
        return {"nodes": [asdict(local_result(config_payload()))], "generated_at": now_iso()}
    rows = await fetch_peers(peers, "/api/open/rag/config", authorization)
    return {"nodes": [asdict(row) for row in rows], "generated_at": now_iso()}


def config_payload() -> dict[str, Any]:
    cfg = dict(SEARCH_CONFIG)
    cfg["node_id"] = node_id()
    cfg["config_name"] = runtime.application.config_name
    cfg["capabilities"] = capabilities()
    cfg["store"] = store_config()
    cfg["dense"] = component_config(runtime.application.config.dense)
    cfg["sparse"] = component_config(runtime.application.config.sparse)
    cfg["parser"] = parser_config()
    cfg["rerank"] = component_config(runtime.application.config.rerank)
    cfg["ocr"] = component_config(runtime.application.config.ocr)
    cfg["available_components"] = runtime.application.config.available_components
    return cfg


def capabilities() -> dict[str, bool]:
    store = runtime.application.store
    sparse = runtime.application.sparse
    return {
        "dense_vector": _supports(store, "supports_dense_vector"),
        "sparse_vector": bool(
            sparse is not None
            and _supports(sparse, "supports_sparse_vector")
            and _supports(store, "supports_sparse_vector", sparse)
        ),
        "search_index": bool(sparse is not None and _supports(sparse, "supports_search_index")),
    }


def _supports(component: Any, method_name: str, *args) -> bool:
    method = getattr(component, method_name, None)
    if not callable(method):
        return False
    return bool(method(*args))


def store_config() -> dict[str, Any]:
    store = runtime.application.config.store
    return {
        "type": store.type,
        "url": store.url,
        "uri": store.uri,
        "persist_dir": store.persist_dir,
        "timeout": store.timeout,
        "import_path": store.import_path,
    }


def parser_config() -> dict[str, Any]:
    parser = runtime.application.config.parser
    return {
        "available": runtime.application.parser.is_available(),
        "enabled": parser.enabled_parser,
        "mineru": {
            "enable": parser.mineru.enable,
            "text": {
                "chunk_size": parser.mineru.text.chunk_size,
                "chunk_overlap": parser.mineru.text.chunk_overlap,
            },
            "table": {
                "header_backward_chars": parser.mineru.table.header_backward_chars,
                "footer_forward_chars": parser.mineru.table.footer_forward_chars,
            },
        },
        "unstructured": {
            "enable": parser.unstructured.enable,
            "strategy": parser.unstructured.strategy,
            "infer_table_structure": parser.unstructured.infer_table_structure,
            "languages": parser.unstructured.languages,
            "text": {
                "chunk_size": parser.unstructured.text.chunk_size,
                "chunk_overlap": parser.unstructured.text.chunk_overlap,
            },
            "table": {
                "header_backward_chars": parser.unstructured.table.header_backward_chars,
                "footer_forward_chars": parser.unstructured.table.footer_forward_chars,
            },
        },
    }


def profile() -> dict[str, Any]:
    return {
        "config_name": runtime.application.config_name,
        "store": store_config(),
        "dense": component_config(runtime.application.config.dense),
        "sparse": component_config(runtime.application.config.sparse),
        "rerank": component_config(runtime.application.config.rerank),
        "ocr": component_config(runtime.application.config.ocr),
    }
