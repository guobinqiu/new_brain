import json

from pydantic import TypeAdapter

from shared.contracts import ParserBlock, ParserFormulaBlock, ParserTableBlock
from shared.upstream import UpstreamServiceError
from services.parser.common.cleaner import clean_parser_blocks
from services.parser.common.schema import Block, FormulaBlock, TableBlock, TextBlock


BLOCKS = TypeAdapter(list[ParserBlock])


def normalize_response_result(result: dict) -> list[Block]:
    if result["status"] != "completed":
        raise UpstreamServiceError(
            service="parser", error="parser document extraction is incomplete or failed",
            retryable=False, status_code=502,
        )
    if not isinstance(result["output"], list):
        raise ValueError("Invalid output list")
    for item in result["output"]:
        if item["type"] == "message":
            if not isinstance(item["content"], list) or item.get("status", "completed") != "completed":
                raise ValueError("Invalid output message")
    output = "".join(
        content["text"]
        for item in result["output"] if item["type"] == "message"
        for content in item["content"] if content["type"] == "output_text"
    )
    blocks = BLOCKS.validate_python(json.loads(output)["blocks"], strict=True)
    return clean_parser_blocks(_to_internal_blocks(blocks), text_separator="\n")


def _to_internal_blocks(blocks: list[ParserBlock]) -> list[Block]:
    normalized = []
    for block in blocks:
        if isinstance(block, ParserTableBlock):
            normalized.append(TableBlock(rows=block.rows, caption=block.caption or "", page=block.page))
        elif isinstance(block, ParserFormulaBlock):
            normalized.append(FormulaBlock(text=block.text, format=block.format, page=block.page))
        else:
            normalized.append(TextBlock(text=block.text, page=block.page, kind=block.kind, level=block.level if block.kind == "heading" else None))
    return normalized
