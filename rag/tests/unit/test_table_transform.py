from rag.parser.chunker import blocks_to_documents, blocks_to_chunks
from rag.parser.schema import TableBlock, TextBlock
from rag.parser.table_transform import table_html_to_blocks
from rag.schema import MineruParserConfig, TableParserConfig, TextParserConfig


def test_table_blocks_carry_context_without_changing_text_blocks():
    config = MineruParserConfig(text=TextParserConfig(chunk_size=200, chunk_overlap=20))
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
        "前置说明文字很长\n\n| 库 | 能力 |\n| --- | --- |\n| Qdrant | 过滤 |\n\n后置说明文字很长",
        "后置说明文字很长",
    ]


def test_table_documents_include_table_metadata():
    config = MineruParserConfig(text=TextParserConfig(chunk_size=200, chunk_overlap=20))
    blocks = [
        TextBlock("表格标题"),
        *table_html_to_blocks(
            "<table><tr><td>库</td><td>能力</td></tr><tr><td>Qdrant</td><td>过滤</td></tr></table>",
            config,
        ),
    ]

    documents = blocks_to_documents(blocks, "report.pdf", config)

    table_documents = [document for document in documents if "| Qdrant | 过滤 |" in document["content"]]
    assert len(table_documents) == 1
    assert table_documents[0]["metadata"]["filename"] == "report.pdf"


def test_table_uses_next_section_title_as_footer_context():
    config = MineruParserConfig(text=TextParserConfig(chunk_size=200, chunk_overlap=20))
    blocks = [
        TextBlock("1. 数据规模对比"),
        *table_html_to_blocks(
            "<table>"
            "<tr><td>向量库</td><td>能力</td></tr>"
            "<tr><td>Qdrant</td><td>过滤</td></tr>"
            "</table>",
            config,
        ),
        TextBlock("2. 查询类型对比"),
        *table_html_to_blocks(
            "<table>"
            "<tr><td>向量库</td><td>查询</td></tr>"
            "<tr><td>Milvus</td><td>混合检索</td></tr>"
            "</table>",
            config,
        ),
    ]

    documents = blocks_to_documents(blocks, "report.pdf", config)
    table_documents = [document for document in documents if "| Qdrant | 过滤 |" in document["content"] or "| Milvus | 混合检索 |" in document["content"]]

    assert len(table_documents) == 2
    assert "2. 查询类型对比" in table_documents[0]["content"]
    assert "2. 查询类型对比" in table_documents[1]["content"]


def test_table_context_uses_configured_backward_and_forward_chars():
    from rag.parser.chunker import blocks_to_documents
    from rag.parser.schema import TableBlock, TextBlock
    from rag.schema import MineruParserConfig, TableParserConfig

    chunks = blocks_to_documents(
        [
            TextBlock("前文" + "A" * 20),
            TableBlock("| 名称 | 大小 |\n| --- | --- |\n| bootstrap | 70MB |"),
            TextBlock("B" * 20 + "后文"),
        ],
        "report.md",
        MineruParserConfig(table=TableParserConfig(header_backward_chars=6, footer_forward_chars=5)),
    )

    assert chunks[1]["content"] == "AAAAAA\n\n| 名称 | 大小 |\n| --- | --- |\n| bootstrap | 70MB |\n\nBBBBB"


def test_table_uses_first_single_cell_row_as_title():
    blocks = table_html_to_blocks(
        "<table>"
        "<tr><td>5. 运维复杂度对比</td><td></td><td></td></tr>"
        "<tr><td>向量库</td><td>安装难度</td><td>集群管理</td></tr>"
        "<tr><td>Qdrant</td><td>Docker</td><td>K8s</td></tr>"
        "</table>",
        MineruParserConfig(),
    )

    assert len(blocks) == 1
    assert blocks[0].text.startswith("5. 运维复杂度对比\n| 向量库 | 安装难度 | 集群管理 |")
    assert "| 5. 运维复杂度对比 | 列2 | 列3 |" not in blocks[0].text
