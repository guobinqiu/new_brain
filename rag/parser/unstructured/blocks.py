import importlib
import os

from rag.parser.common.schema import Block, TableBlock, TextBlock
from rag.parser.common.table_transform import table_html_to_blocks
from rag.schema import UnstructuredParserConfig


def partition_blocks(filepath: str, config: UnstructuredParserConfig) -> list[Block]:
    return elements_to_blocks(partition_file(filepath, config), config, os.path.splitext(filepath)[1].lower())


def partition_file(filepath: str, config: UnstructuredParserConfig):
    try:
        partition = importlib.import_module("unstructured.partition.auto").partition
    except ImportError as exc:
        raise RuntimeError("unstructured parser is not installed") from exc
    return partition(
        filename=filepath,
        strategy=config.strategy,
        infer_table_structure=config.infer_table_structure,
        languages=config.languages,
    )


def elements_to_blocks(elements, config: UnstructuredParserConfig, ext: str = "") -> list[Block]:
    blocks: list[Block] = []
    for element in elements:
        text = element_text(element)
        if not text:
            continue
        if is_table_element(element):
            text_as_html = element_text_as_html(element)
            if text_as_html:
                blocks.extend(table_html_to_blocks(text_as_html, config))
            else:
                blocks.append(TableBlock(text))
        else:
            blocks.append(TextBlock(text, kind=element_text_kind(element, ext)))
    return blocks


def element_text_kind(element, ext: str) -> str:
    category = getattr(element, "category", None) or element.__class__.__name__
    if ext == ".pdf":
        return "line"
    if category == "Title":
        return "section_title"
    if category == "ListItem":
        return "list_item"
    return "paragraph"


def element_text(element) -> str:
    text_as_html = element_text_as_html(element)
    if text_as_html and is_table_element(element):
        return text_as_html
    return str(element).strip()


def element_text_as_html(element) -> str:
    metadata = getattr(element, "metadata", None)
    text_as_html = getattr(metadata, "text_as_html", None) if metadata is not None else None
    return str(text_as_html).strip() if text_as_html else ""


def is_table_element(element) -> bool:
    category = getattr(element, "category", None)
    if category == "Table":
        return True
    return element.__class__.__name__ == "Table"
