import importlib

import pytest


pytestmark = pytest.mark.unit


def test_mineru_provider_package_does_not_expose_local_engine_entrypoints():
    mineru = importlib.import_module("services.parser.providers.mineru")

    assert not hasattr(mineru, "parse_document_blocks")
    assert not hasattr(mineru, "load_table_parser")
    assert not hasattr(mineru, "prepare_mineru_runtime_config")
