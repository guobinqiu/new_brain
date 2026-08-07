from __future__ import annotations


def auto_device() -> str:
    try:
        torch = _load_torch()
    except Exception:
        return "cpu"
    try:
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _load_torch():
    import torch

    return torch
