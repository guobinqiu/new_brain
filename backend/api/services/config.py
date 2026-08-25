import os
from dataclasses import asdict
from typing import Any

from api.runtime import runtime
from api.services.common import component_config, now_iso
from config import SEARCH_CONFIG
from nodes import fetch_peers, local_result, node_id, parse_peers


def get_config(_):
    return config_payload()


async def nodes_config(authorization: str | None, _):
    peers = parse_peers(os.getenv("RAG_PEERS"))
    if not peers:
        return {"nodes": [asdict(local_result(config_payload()))], "generated_at": now_iso()}
    rows = await fetch_peers(peers, "/api/config", authorization)
    return {"nodes": [asdict(row) for row in rows], "generated_at": now_iso()}


def config_payload() -> dict[str, Any]:
    cfg = dict(SEARCH_CONFIG)
    cfg["node_id"] = node_id()
    cfg["config_name"] = runtime.application.config_name
    cfg["store"] = store_config()
    cfg["dense"] = component_config(runtime.application.config.dense)
    cfg["sparse"] = component_config(runtime.application.config.sparse)
    cfg["parser"] = parser_config()
    cfg["rerank"] = component_config(runtime.application.config.rerank)
    cfg["ocr"] = component_config(runtime.application.config.ocr)
    cfg["available_components"] = runtime.application.config.available_components
    return cfg


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
        "type": parser.type,
        "available": [
            {"name": "standard", "available": runtime.application.parser.is_available("standard")},
            {"name": "fast", "available": True},
        ],
        "text": {
            "chunk_size": parser.text.chunk_size,
            "chunk_overlap": parser.text.chunk_overlap,
        },
        "table": {
            "chunk_size": parser.table.chunk_size,
            "before_text_size": parser.table.before_text_size,
            "after_text_size": parser.table.after_text_size,
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
