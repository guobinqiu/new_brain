from __future__ import annotations

from typing import Protocol


class OCR(Protocol):
    ready: bool

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def image_to_text(self, image_path: str) -> str:
        ...
