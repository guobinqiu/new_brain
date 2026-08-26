from dataclasses import dataclass, field


@dataclass
class TextBlock:
    text: str
    kind: str = "text"


@dataclass
class TableBlock:
    text: str
    table_key: object = field(default_factory=object)
    table_part_index: int = 0
    table_part_count: int = 1
    before: str = ""
    after: str = ""


@dataclass
class ImageBlock:
    text: str


Block = TextBlock | TableBlock | ImageBlock
