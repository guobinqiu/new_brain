import os
from dataclasses import asdict
from typing import Any

from api.runtime import runtime
from api.services.common import component_config, component_model, component_status, now_iso
from api.services.config import profile
from nodes import fetch_peers, local_result, node_id, parse_peers


def monitor(_):
    return monitor_payload()


async def nodes_monitor(authorization: str | None, _):
    peers = parse_peers(os.getenv("RAG_PEERS"))
    if not peers:
        return {"nodes": [asdict(local_result(monitor_payload()))], "generated_at": now_iso()}
    rows = await fetch_peers(peers, "/api/monitor", authorization)
    return {"nodes": [asdict(row) for row in rows], "generated_at": now_iso()}


def monitor_payload() -> dict[str, Any]:
    return {
        "node_id": node_id(),
        "ready": runtime.application.ready,
        "profile": profile(),
        "components": components(),
        "capabilities": capabilities(),
        "index_contract": index_contract(),
    }


def capabilities() -> dict[str, Any]:
    return {
        "search_modes": ["dense", "sparse", "hybrid"],
        "rerank": runtime.application.rerank is not None,
        "ocr": runtime.application.ocr is not None,
        "config_write": False,
        "restart": False,
    }


def index_contract() -> dict[str, Any]:
    return {
        "dense": component_config(runtime.application.config.dense),
        "sparse": component_config(runtime.application.config.sparse),
        "rerank": component_config(runtime.application.config.rerank),
        "ocr": component_config(runtime.application.config.ocr),
    }


def components() -> list[dict[str, Any]]:
    sparse_error = runtime.application.component_errors.get("sparse")
    return [
        {
            "name": "Store",
            "status": component_status(runtime.application.store, enabled=runtime.application.config.store is not None, error=runtime.application.component_errors.get("store")),
            "model": runtime.application.config.store.type,
        },
        {
            "name": "Dense",
            "status": component_status(runtime.application.dense, enabled=runtime.application.config.dense is not None, error=runtime.application.component_errors.get("dense")),
            "model": component_model(runtime.application.config.dense),
        },
        {
            "name": "Sparse",
            "status": component_status(runtime.application.sparse, enabled=runtime.application.config.sparse is not None, error=sparse_error),
            "model": component_model(runtime.application.config.sparse),
        },
        {
            "name": "Rerank",
            "status": component_status(runtime.application.rerank, enabled=runtime.application.config.rerank is not None, error=runtime.application.component_errors.get("rerank")),
            "model": component_model(runtime.application.config.rerank),
        },
        {
            "name": "OCR",
            "status": component_status(runtime.application.ocr, enabled=runtime.application.config.ocr is not None, error=runtime.application.component_errors.get("ocr")),
            "model": component_model(runtime.application.config.ocr),
        },
        {
            "name": "Parser",
            "status": component_status(runtime.application.parser, enabled=True, error=runtime.application.component_errors.get("parser")),
            "model": runtime.application.config.parser.type,
        },
        {
            "name": "database",
            "status": component_status(runtime.application.database, enabled=True, error=runtime.application.component_errors.get("database")),
        },
    ]
