from __future__ import annotations


def disable_model_progress_bars() -> None:
    from huggingface_hub.utils import disable_progress_bars
    from transformers.utils import logging as transformers_logging

    disable_progress_bars()
    transformers_logging.disable_progress_bar()
