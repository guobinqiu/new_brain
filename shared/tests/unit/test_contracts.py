from pydantic import TypeAdapter

from shared.contracts import ErrorResponse, ParserBlock, ParserTextBlock, ParserTableBlock, ParserFormulaBlock, EmbeddingRequest, EmbeddingResponse, RerankRequest, RerankResponse


def test_error_response_carries_error_trace_and_retryable():
    response = ErrorResponse(error="unsupported", traceId="a" * 32, retryable=False)

    assert response.model_dump() == {
        "error": "unsupported",
        "traceId": "a" * 32,
        "retryable": False,
    }


def test_parser_block_contract_selects_model_by_type():
    adapter = TypeAdapter(list[ParserBlock])
    blocks = adapter.validate_python([
        {"type": "text", "text": "hello"},
        {"type": "table", "rows": [["Name"], ["alpha"]]},
        {"type": "formula", "text": "a+b", "format": "latex", "page": 2},
    ])

    assert blocks == [
        ParserTextBlock(text="hello"),
        ParserTableBlock(rows=[["Name"], ["alpha"]]),
        ParserFormulaBlock(text="a+b", page=2),
    ]


def test_embedding_contract_supports_dense_vectors():
    request = EmbeddingRequest(texts=["a", "b"])
    response = EmbeddingResponse(vectors=[[0.1, 0.2], [0.3, 0.4]])

    assert request.texts == ["a", "b"]
    assert response.vectors[1] == [0.3, 0.4]


def test_rerank_contract_returns_ordered_scores():
    request = RerankRequest(query="q", documents=["a", "b"], top_k=1)
    response = RerankResponse(results=[{"index": 1, "score": 0.9}])

    assert request.top_k == 1
    assert response.results == [{"index": 1, "score": 0.9}]
