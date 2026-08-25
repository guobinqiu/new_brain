from parser.table_transform import TableBlock, TextBlock, blocks_to_chunks, table_html_to_blocks
from schema import ParserConfig, ParserTableConfig, ParserTextConfig


def test_table_blocks_carry_context_without_changing_text_blocks():
    config = ParserConfig(
        type="text",
        text=ParserTextConfig(chunk_size=200, chunk_overlap=20),
        table=ParserTableConfig(chunk_size=1000, before_text_size=4, after_text_size=4),
    )
    blocks = [
        TextBlock("前置说明文字很长"),
        *table_html_to_blocks(
            "<table><tr><td>库</td><td>能力</td></tr><tr><td>Qdrant</td><td>过滤</td></tr></table>",
            config,
        ),
        TextBlock("后置说明文字很长"),
    ]

    chunks = blocks_to_chunks(blocks, config)

    assert isinstance(blocks[0], TextBlock)
    assert isinstance(blocks[1], TableBlock)
    assert isinstance(blocks[2], TextBlock)
    assert chunks == [
        "前置说明文字很长",
        "文字很长\n\n库: Qdrant；能力: 过滤\n\n后置说明",
        "后置说明文字很长",
    ]
