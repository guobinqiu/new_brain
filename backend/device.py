from __future__ import annotations

import gc


def auto_device() -> str:
    try:
        torch = _load_torch()
    except Exception:
        return "cpu"
    try:
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def release_memory() -> None:
    gc.collect()
    try:
        torch = _load_torch()
    except Exception:
        return
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        return


def _load_torch():
    import torch

    return torch
