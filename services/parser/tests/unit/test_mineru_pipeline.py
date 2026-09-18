import pytest


pytestmark = pytest.mark.unit


def test_mineru_content_list_merges_text_fragments_and_drops_table_duplicates():
    from services.parser.common.schema import TableBlock
    from services.parser.providers.mineru.normalizer import content_list_to_blocks

    blocks = content_list_to_blocks(
        [
            {"type": "text", "text": "稀疏向", "page_idx": 0},
            {"type": "text", "text": "量", "page_idx": 0},
            {"type": "text", "text": "/", "page_idx": 0},
            {
                "type": "table",
                "table_body": (
                    "<table>"
                    "<tr><td>稀疏向量/关键词搜索</td><td>支持情况</td></tr>"
                    "<tr><td>Milvus</td><td>支持</td></tr>"
                    "</table>"
                ),
                "page_idx": 0,
            },
        ],
    )

    assert blocks == [
        TableBlock(
            rows=[["稀疏向量/关键词搜索", "支持情况"], ["Milvus", "支持"]],
            page=1,
        ),
    ]
def test_mineru_preserves_native_heading_list_and_code():
    from services.parser.common.schema import TextBlock
    from services.parser.providers.mineru.normalizer import content_list_to_blocks

    blocks = content_list_to_blocks([
        {"type": "text", "text_level": 1, "text": "Title", "page_idx": 0},
        {"type": "list", "list_items": ["First", "Second"], "page_idx": 0},
        {"type": "code", "code_body": "if x < 1:\n    print(x)\n\n", "page_idx": 0},
    ])
    assert blocks == [TextBlock("Title", page=1, kind="heading"),
                      TextBlock("First", page=1, kind="list_item"),
                      TextBlock("Second", page=1, kind="list_item"),
                      TextBlock("if x < 1:\n    print(x)", page=1, kind="code")]
