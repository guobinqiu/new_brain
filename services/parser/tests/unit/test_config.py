import pytest


pytestmark = pytest.mark.unit


def _parser_yaml(raw):
    import yaml

    return yaml.safe_dump(raw)


def test_load_parser_config_selects_enabled_docling(tmp_path):
    import yaml
    from services.parser.app.config import load_parser_config

    path = tmp_path / "parser.yaml"
    path.write_text(
        _parser_yaml({
            "parser": {
                "mineru": {
                    "enable": False,
                    "parse_method": "ocr",
                    "formula": True,
                    "table": True,
                },
                "mineru_vlm": {"enable": False},
                "docling": {
                    "enable": True,
                    "formula": True,
                    "table": True,
                },
                "docling_vlm": {
                    "enable": False,
                    "model": "granitedocling",
                },
            },
        }),
        encoding="utf-8",
    )

    config = load_parser_config(path)

    assert config.active == "docling"
    assert config.mineru.parse_method == "ocr"
    assert config.docling.formula is True
    assert config.docling.table_enable is True
    assert not hasattr(config.mineru_vlm, "formula")
    assert not hasattr(config.mineru_vlm, "table_enable")
    assert config.docling_vlm.model == "granitedocling"


def test_load_parser_config_selects_enabled_docling_vlm(tmp_path):
    import yaml
    from services.parser.app.config import load_parser_config

    path = tmp_path / "parser.yaml"
    path.write_text(
        _parser_yaml({
            "parser": {
                "mineru": {"enable": False},
                "mineru_vlm": {"enable": False},
                "docling": {"enable": False},
                "docling_vlm": {"enable": True, "model": "granitedocling"},
            },
        }),
        encoding="utf-8",
    )

    config = load_parser_config(path)

    assert config.active == "docling_vlm"
    assert config.docling_vlm.model == "granitedocling"


def test_load_parser_config_rejects_no_enabled_backend(tmp_path):
    import yaml
    from services.parser.app.config import load_parser_config

    path = tmp_path / "parser.yaml"
    path.write_text(
        _parser_yaml({
            "parser": {
                "mineru": {"enable": False},
                "mineru_vlm": {"enable": False},
                "docling": {"enable": False},
                "docling_vlm": {"enable": False},
            },
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="parser must enable exactly one backend"):
        load_parser_config(path)


def test_load_parser_config_rejects_multiple_enabled_backends(tmp_path):
    import yaml
    from services.parser.app.config import load_parser_config

    path = tmp_path / "parser.yaml"
    path.write_text(
        _parser_yaml({
            "parser": {
                "mineru": {"enable": True},
                "mineru_vlm": {"enable": False},
                "docling": {"enable": True},
                "docling_vlm": {"enable": False},
            },
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="parser must enable exactly one backend"):
        load_parser_config(path)


def test_load_parser_config_docling_table_mode_defaults_to_accurate(tmp_path):
    import yaml
    from services.parser.app.config import load_parser_config

    path = tmp_path / "parser.yaml"
    path.write_text(
        _parser_yaml({
            "parser": {
                "mineru": {"enable": False},
                "mineru_vlm": {"enable": False},
                "docling": {"enable": True, "formula": True, "table": True},
                "docling_vlm": {"enable": False},
            },
        }),
        encoding="utf-8",
    )

    config = load_parser_config(path)

    assert config.docling.table_mode == "accurate"


@pytest.mark.parametrize("table_mode", ["fast", "accurate"])
def test_load_parser_config_docling_table_mode_passthrough(tmp_path, table_mode):
    import yaml
    from services.parser.app.config import load_parser_config

    path = tmp_path / "parser.yaml"
    path.write_text(
        _parser_yaml({
            "parser": {
                "mineru": {"enable": False},
                "mineru_vlm": {"enable": False},
                "docling": {"enable": True, "table_mode": table_mode},
                "docling_vlm": {"enable": False},
            },
        }),
        encoding="utf-8",
    )

    config = load_parser_config(path)

    assert config.docling.table_mode == table_mode


def test_load_parser_config_rejects_invalid_docling_table_mode(tmp_path):
    import yaml
    from services.parser.app.config import load_parser_config

    path = tmp_path / "parser.yaml"
    path.write_text(
        _parser_yaml({
            "parser": {
                "mineru": {"enable": False},
                "mineru_vlm": {"enable": False},
                "docling": {"enable": True, "table_mode": "turbo"},
                "docling_vlm": {"enable": False},
            },
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="docling.table_mode"):
        load_parser_config(path)
