import pytest


pytestmark = pytest.mark.unit


def test_docling_preserves_element_categories_and_code_whitespace():
    from docling_core.types.doc import DoclingDocument, DocItemLabel
    from services.parser.providers.docling.normalizer import normalize_docling_document

    document = DoclingDocument(name="structure")
    document.add_heading(text="Title", level=1)
    document.add_text(label=DocItemLabel.PARAGRAPH, text="Paragraph")
    document.add_list_item(text="Item", parent=document.add_list_group())
    document.add_code(text="    print(x)\n\n    print(y)")
    document.add_text(label=DocItemLabel.TEXT, text="Other")
    blocks = normalize_docling_document(document)
    assert [block.kind for block in blocks] == ["heading", "paragraph", "list_item", "code", "text"]
    assert blocks[3].text == "    print(x)\n\n    print(y)"


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("caption_texts", [["Table 1"], ["Table 1 ", " Results"]])
def test_docling_normalizer_preserves_table_caption_refs_without_duplicate_text(nested, caption_texts):
    from docling_core.types.doc import DoclingDocument, DocItemLabel, TableCell, TableData
    from services.parser.common.schema import TableBlock, TextBlock
    from services.parser.providers.docling.normalizer import normalize_docling_document

    document = DoclingDocument(name="table-caption")
    parent = document.add_group() if nested else document.body
    document.add_text(label=DocItemLabel.TEXT, text="Surrounding paragraph", parent=parent)
    captions = [
        document.add_text(label=DocItemLabel.CAPTION, text=text, parent=parent)
        for text in caption_texts
    ]
    table = document.add_table(
        data=TableData(num_rows=1, num_cols=1, table_cells=[
            TableCell(text="Value", start_row_offset_idx=0, end_row_offset_idx=1,
                      start_col_offset_idx=0, end_col_offset_idx=1),
        ]),
        caption=captions[0],
        parent=parent,
    )
    table.captions.extend(caption.get_ref() for caption in captions[1:])

    assert normalize_docling_document(document) == [
        TextBlock("Surrounding paragraph"),
        TableBlock(rows=[["Value"]], caption=" ".join("".join(caption_texts).split())),
    ]


def test_docling_parser_normalizes_document_structure():
    from services.parser.providers.docling.pdf_pipeline import DoclingPipelineDocumentParser
    from services.parser.common.schema import FormulaBlock, TableBlock, TextBlock
    from shared.config import DoclingParserConfig
    class FakeDocument:
        def export_to_dict(self):
            return {
                "body": {
                    "children": [
                        {"$ref": "#/texts/0"},
                        {"$ref": "#/tables/0"},
                        {"$ref": "#/texts/1"},
                        {"$ref": "#/pictures/0"},
                    ],
                },
                "texts": [
                    {"self_ref": "#/texts/0", "label": "text", "text": "正文", "prov": [{"page_no": 1}]},
                    {"self_ref": "#/texts/1", "label": "formula", "text": "E=mc^2", "prov": [{"page_no": 2}]},
                ],
                "tables": [
                    {
                        "self_ref": "#/tables/0",
                        "captions": [],
                        "prov": [{"page_no": 1}],
                        "data": {
                            "num_rows": 2,
                            "num_cols": 2,
                            "table_cells": [
                                {"text": "A", "start_row_offset_idx": 0, "end_row_offset_idx": 1, "start_col_offset_idx": 0, "end_col_offset_idx": 1},
                                {"text": "B", "start_row_offset_idx": 0, "end_row_offset_idx": 1, "start_col_offset_idx": 1, "end_col_offset_idx": 2},
                                {"text": "1", "start_row_offset_idx": 1, "end_row_offset_idx": 2, "start_col_offset_idx": 0, "end_col_offset_idx": 1},
                                {"text": "2", "start_row_offset_idx": 1, "end_row_offset_idx": 2, "start_col_offset_idx": 1, "end_col_offset_idx": 2},
                            ],
                        },
                    },
                ],
                "pictures": [
                    {"self_ref": "#/pictures/0", "label": "picture"},
                ],
            }

    class FakeResult:
        document = FakeDocument()

    class FakeConverter:
        def convert(self, filepath):
            assert filepath == "/tmp/example.pdf"
            return FakeResult()

    parser = DoclingPipelineDocumentParser(DoclingParserConfig())
    parser.converter = FakeConverter()

    blocks = parser.parse_file("/tmp/example.pdf", original_filename="example.pdf")

    assert blocks == [
        TextBlock("正文", page=1),
        TableBlock(rows=[["A", "B"], ["1", "2"]], page=1),
        FormulaBlock("E=mc^2", page=2),
    ]


def test_docling_normalizer_merges_consecutive_text_fragments():
    from services.parser.common.schema import TextBlock
    from services.parser.providers.docling.normalizer import normalize_docling_document

    class FakeDocument:
        def export_to_dict(self):
            return {
                "body": {
                    "children": [
                        {"$ref": "#/texts/0"},
                        {"$ref": "#/texts/1"},
                        {"$ref": "#/texts/2"},
                    ],
                },
                "texts": [
                    {"self_ref": "#/texts/0", "label": "text", "text": "稀疏向", "prov": [{"page_no": 1}]},
                    {"self_ref": "#/texts/1", "label": "text", "text": "量", "prov": [{"page_no": 1}]},
                    {"self_ref": "#/texts/2", "label": "text", "text": "关键词搜索", "prov": [{"page_no": 1}]},
                ],
            }

    assert normalize_docling_document(FakeDocument()) == [
        TextBlock("稀疏向量关键词搜索", page=1),
    ]


def test_docling_normalizer_drops_table_cell_text_fragments():
    from services.parser.common.schema import TableBlock
    from services.parser.providers.docling.normalizer import normalize_docling_document

    class FakeDocument:
        def export_to_dict(self):
            return {
                "body": {
                    "children": [
                        {"$ref": "#/texts/0"},
                        {"$ref": "#/texts/1"},
                        {"$ref": "#/texts/2"},
                        {"$ref": "#/tables/0"},
                    ],
                },
                "texts": [
                    {"self_ref": "#/texts/0", "label": "text", "text": "稀疏向", "prov": [{"page_no": 1}]},
                    {"self_ref": "#/texts/1", "label": "text", "text": "量", "prov": [{"page_no": 1}]},
                    {"self_ref": "#/texts/2", "label": "text", "text": "/", "prov": [{"page_no": 1}]},
                ],
                "tables": [
                    {
                        "self_ref": "#/tables/0",
                        "prov": [{"page_no": 1}],
                        "data": {
                            "num_rows": 2,
                            "num_cols": 2,
                            "table_cells": [
                                {"text": "稀疏向量/关键词搜索", "start_row_offset_idx": 0, "start_col_offset_idx": 0},
                                {"text": "支持情况", "start_row_offset_idx": 0, "start_col_offset_idx": 1},
                                {"text": "Milvus", "start_row_offset_idx": 1, "start_col_offset_idx": 0},
                                {"text": "支持", "start_row_offset_idx": 1, "start_col_offset_idx": 1},
                            ],
                        },
                    },
                ],
            }

    assert normalize_docling_document(FakeDocument()) == [
        TableBlock(
            rows=[["稀疏向量/关键词搜索", "支持情况"], ["Milvus", "支持"]],
            page=1,
        ),
    ]


@pytest.mark.parametrize("table_mode, expected", [("accurate", "ACCURATE"), ("fast", "FAST")])
def test_docling_pipeline_table_mode_configures_tableformer_mode(table_mode, expected):
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import TableFormerMode
    from services.parser.providers.docling.pdf_pipeline import DoclingPipelineDocumentParser
    from shared.config import DoclingParserConfig

    parser = DoclingPipelineDocumentParser(DoclingParserConfig(table_mode=table_mode))

    converter = parser._build_converter()

    options = converter.format_to_options[InputFormat.PDF]
    assert options.pipeline_options.table_structure_options.mode is TableFormerMode[expected]


def test_docling_pipeline_rejects_invalid_table_mode():
    from services.parser.providers.docling.pdf_pipeline import DoclingPipelineDocumentParser
    from shared.config import DoclingParserConfig

    parser = DoclingPipelineDocumentParser(DoclingParserConfig(table_mode="turbo"))

    with pytest.raises(ValueError, match="table_mode"):
        parser._build_converter()
