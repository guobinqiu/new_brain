from dataclasses import dataclass


@dataclass
class TextBlock:
    text: str
    kind: str = "text"


@dataclass
class TableBlock:
    text: str
    header: str = ""
    footer: str = ""


@dataclass
class ImageBlock:
    path: str
    file_type: str


Block = TextBlock | TableBlock | ImageBlock
