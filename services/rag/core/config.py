from __future__ import annotations

from services.rag.core.loader import load_app_config


CONFIG = load_app_config()

SEARCH_CONFIG = {
    "top_k": CONFIG.search.top_k,
}
