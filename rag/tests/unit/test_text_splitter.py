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


def test_blocks_to_chunks_merge_layout_lines_without_merging_paragraphs():
    from rag.parser.common.chunker import blocks_to_chunks
    from rag.parser.common.schema import TextBlock
    from rag.schema import MineruParserConfig, TextParserConfig

    config = MineruParserConfig(text=TextParserConfig(chunk_size=500, chunk_overlap=80))

    chunks = blocks_to_chunks(
        [
            TextBlock("第一段说明合同履行背景。", kind="paragraph"),
            TextBlock("PDF 抽取出来的第一行", kind="line"),
            TextBlock("PDF 抽取出来的第二行", kind="line"),
            TextBlock("第二段说明代理制度背景。", kind="paragraph"),
        ],
        config,
    )

    assert chunks == [
        "第一段说明合同履行背景。",
        "PDF 抽取出来的第一行\nPDF 抽取出来的第二行",
        "第二段说明代理制度背景。",
    ]


def test_blocks_to_chunks_do_not_merge_layout_lines_across_tables_or_titles():
    from rag.parser.common.chunker import blocks_to_chunks
    from rag.parser.common.schema import TableBlock, TextBlock
    from rag.schema import MineruParserConfig, TextParserConfig

    config = MineruParserConfig(text=TextParserConfig(chunk_size=500, chunk_overlap=80))

    chunks = blocks_to_chunks(
        [
            TextBlock("PDF 表格前第一行", kind="line"),
            TextBlock("PDF 表格前第二行", kind="line"),
            TableBlock("| 名称 | 能力 |\n| --- | --- |\n| Qdrant | 过滤 |"),
            TextBlock("1. 新章节", kind="section_title"),
            TextBlock("PDF 新章节第一行", kind="line"),
            TextBlock("PDF 新章节第二行", kind="line"),
        ],
        config,
    )

    assert chunks == [
        "PDF 表格前第一行\nPDF 表格前第二行",
        "PDF 表格前第一行\nPDF 表格前第二行\n\n| 名称 | 能力 |\n| --- | --- |\n| Qdrant | 过滤 |\n\n1. 新章节",
        "1. 新章节",
        "PDF 新章节第一行\nPDF 新章节第二行",
    ]


def test_blocks_to_chunks_merge_consecutive_list_items():
    from rag.parser.common.chunker import blocks_to_chunks
    from rag.parser.common.schema import TextBlock
    from rag.schema import MineruParserConfig, TextParserConfig

    config = MineruParserConfig(text=TextParserConfig(chunk_size=500, chunk_overlap=80))

    chunks = blocks_to_chunks(
        [
            TextBlock("入住材料", kind="section_title"),
            TextBlock("身份证", kind="list_item"),
            TextBlock("订单号", kind="list_item"),
            TextBlock("押金凭证", kind="list_item"),
            TextBlock("退房规则说明。", kind="paragraph"),
        ],
        config,
    )

    assert chunks == [
        "入住材料",
        "身份证\n订单号\n押金凭证",
        "退房规则说明。",
    ]


def test_unstructured_pdf_title_elements_are_treated_as_layout_lines():
    from rag.parser.unstructured.blocks import element_text_kind

    class Element:
        category = "Title"

    assert element_text_kind(Element(), ".pdf") == "line"
