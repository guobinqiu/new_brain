import pytest

from services.parser.common.cleaner import clean_parser_blocks
from services.parser.common.normalizer import normalize_blocks
from services.parser.common.schema import TableBlock, TextBlock


def test_text_block_preserves_kind():
    block = TextBlock("title", page=2, kind="heading")
    assert vars(block) == {"text": "title", "page": 2, "kind": "heading", "level": None}
    assert normalize_blocks([block]) == [block]


def test_heading_level_survives_normalization_and_http_contract():
    from services.parser.app.main import _block_response

    block = TextBlock(" Title ", page=2, kind="heading", level=3)
    normalized = normalize_blocks([block])[0]
    assert normalized.level == 3
    assert _block_response(normalized).model_dump()["level"] == 3


def test_pdf_cleaner_preserves_structured_boundaries_and_repairs_unknown_text():
    blocks = [
        TextBlock("Title", page=1, kind="heading"),
        TextBlock("Paragraph", page=1, kind="paragraph"),
        TextBlock("Item", page=1, kind="list_item"),
        TextBlock("x = 1\n\nprint(x)", page=1, kind="code"),
        TextBlock("稀疏向", page=1), TextBlock("量", page=1),
    ]
    assert clean_parser_blocks(blocks) == blocks[:4] + [TextBlock("稀疏向量", page=1)]


@pytest.mark.parametrize("kind", ["heading", "paragraph", "list_item", "code"])
def test_cleaner_does_not_drop_structured_content_found_in_a_table(kind):
    text = TextBlock("A", page=1, kind=kind)
    table = TableBlock(rows=[["A"], ["1"]], page=1)
    assert clean_parser_blocks([text, table]) == [text, table]


def test_code_normalization_preserves_indentation():
    block = TextBlock("    print(x)\n\n    print(y)", kind="code")
    assert normalize_blocks([block]) == [block]


def test_table_block_contains_only_rows_caption_and_page():
    block = TableBlock(rows=[["A"], ["1"]], caption="Table", page=2)
    assert vars(block) == {"rows": [["A"], ["1"]], "caption": "Table", "page": 2}


@pytest.mark.parametrize("text", [" 1. Title ", " body "])
def test_normalizer_preserves_page(text):
    assert normalize_blocks([TextBlock(text, page=3)]) == [
        TextBlock(text.strip(), page=3),
    ]


@pytest.mark.parametrize("text", ["Table title", "A 1"])
def test_cleaner_deduplicates_rows_and_caption_on_same_page(text):
    table = TableBlock(rows=[["A"], ["1"]], caption="Table title", page=2)
    other_page = TextBlock(text, page=3)
    assert clean_parser_blocks([TextBlock(text, page=2), table, other_page]) == [
        table, other_page,
    ]
