import os
from dataclasses import asdict
from typing import Any

from rag.api.runtime import runtime
from rag.api.services.common import component_config, component_model, component_status, now_iso, required_component_status
from rag.api.services.config import profile
from rag.nodes import fetch_peers, local_result, node_id, parse_peers


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
            "status": required_component_status(runtime.application.store, error=runtime.application.component_errors.get("store")),
            "model": runtime.application.config.store.type,
        },
        {
            "name": "Dense",
            "status": required_component_status(runtime.application.dense, error=runtime.application.component_errors.get("dense")),
            "model": component_model(runtime.application.config.dense),
        },
        {
            "name": "Sparse",
            "status": required_component_status(runtime.application.sparse, error=sparse_error),
            "model": component_model(runtime.application.config.sparse),
        },
        {
            "name": "Rerank",
            "status": component_status(runtime.application.rerank, enabled=runtime.application.config.rerank is not None, error=runtime.application.component_errors.get("rerank")),
            "model": component_model(runtime.application.config.rerank),
        },
        {
            "name": "OCR",
            "status": required_component_status(runtime.application.ocr, error=runtime.application.component_errors.get("ocr")),
            "model": component_model(runtime.application.config.ocr),
        },
        parser_component(),
        {
            "name": "database",
            "status": required_component_status(runtime.application.database, error=runtime.application.component_errors.get("database")),
        },
    ]


def parser_component() -> dict[str, Any]:
    parser = runtime.application.config.parser
    component = {
        "name": "Parser",
        "status": parser_status(),
        "model": parser.enabled_parser,
    }
    if parser.enabled_parser == "unstructured":
        component["mode"] = parser.unstructured.strategy
    return component


def parser_status() -> str:
    error = runtime.application.component_errors.get("parser")
    if error:
        return "error"
    if not runtime.application.ready:
        return "loading"
    return "ready" if runtime.application.parser.is_available() else "error"
