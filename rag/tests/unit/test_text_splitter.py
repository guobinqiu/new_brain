from rag.parser.common.text_splitter import split_paragraphs, split_text


def test_split_paragraphs_keeps_blank_line_paragraphs_separate():
    text = "第一段说明合同履行背景。\n\n第二段说明代理制度背景。"

    chunks = split_paragraphs(text)

    assert chunks == ["第一段说明合同履行背景。", "第二段说明代理制度背景。"]


def test_split_text_splits_single_text_block_over_limit():
    long = "很长的代理制度说明。" * 80

    chunks = split_text(long, chunk_size=120, overlap=20)

    assert len(chunks) > 1
    assert max(len(chunk) for chunk in chunks) <= 120


def test_blocks_to_chunks_keep_text_blocks_separate():
    from rag.parser.common.chunker import blocks_to_chunks
    from rag.parser.common.schema import TextBlock
    from rag.schema import MineruParserConfig, TextParserConfig

    config = MineruParserConfig(text=TextParserConfig(chunk_size=500, chunk_overlap=80))

    chunks = blocks_to_chunks(
        [
            TextBlock("第一段说明合同履行背景。"),
            TextBlock("第二段说明代理制度背景。"),
        ],
        config,
    )

    assert chunks == ["第一段说明合同履行背景。", "第二段说明代理制度背景。"]
