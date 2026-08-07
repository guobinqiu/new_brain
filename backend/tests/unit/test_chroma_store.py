from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


def test_chroma_store_resolves_persist_dir_from_project_root(tmp_path):
    from store import chroma

    project_root = tmp_path / "rag"
    project_root.mkdir()

    path = chroma._persist_path("chroma_data/native", project_root=project_root)

    assert path == str(project_root / "chroma_data" / "native")
    assert (project_root / "chroma_data" / "native").is_dir()


def test_chroma_store_keeps_absolute_persist_dir(tmp_path):
    from store import chroma

    persist_dir = tmp_path / "absolute_chroma"

    assert chroma._persist_path(str(persist_dir)) == str(persist_dir)
