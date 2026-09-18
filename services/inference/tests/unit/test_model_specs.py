from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from starlette.datastructures import State

from services.inference.app.main import app, models, EmbeddingsRequest
from services.inference.providers.siliconflow import SiliconFlowDenseClient


pytestmark = pytest.mark.unit


def test_models_returns_specs_without_encoding_known_dimensions(monkeypatch):
    encode = Mock(side_effect=AssertionError("must not encode"))
    monkeypatch.setattr(app, "state", State({
        "dense": SimpleNamespace(ready=True, model_name="local-dense", vector_size=768, embed_query=encode),
        "sparse": SimpleNamespace(ready=True, model="sparse-model"),
        "rerank": None,
    }))
    assert models() == {
        "dense": {"model_name": "local-dense", "dimensions": 768},
        "sparse": {"model_name": "sparse-model"},
        "rerank": None,
    }


def test_external_unknown_dimension_is_probed_once_and_cached():
    dense = SiliconFlowDenseClient("http://inference", model="test")
    dense.embed_query = Mock(return_value=[0.1, 0.2])
    try:
        assert dense.vector_size == 2
        assert dense.vector_size == 2
        dense.embed_query.assert_called_once_with("dimension probe")
    finally:
        dense.close()


def test_external_explicit_dimensions_do_not_probe():
    dense = SiliconFlowDenseClient("http://inference", model="test", dimensions=768)
    dense.embed_query = Mock(side_effect=AssertionError("must not encode"))
    try:
        assert dense.vector_size == 768
    finally:
        dense.close()


@pytest.mark.parametrize("value", [42, {"text": "query"}, [], ""])
def test_embedding_endpoints_reject_invalid_input(value):
    with pytest.raises(ValidationError):
        EmbeddingsRequest(input=value)
