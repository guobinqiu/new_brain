import importlib.util
import json
import os
import tempfile
from pathlib import Path

import shared.device as device
from services.parser.common.schema import Block
from services.parser.common.validation import validate_pdf_file
from services.parser.providers.mineru.normalizer import read_content_list_blocks
from shared.config import MineruParserConfig
from shared.paths import MODELS_DIR


MINERU_DIR = MODELS_DIR / "mineru"


def table_parser_available() -> bool:
    return importlib.util.find_spec("mineru") is not None and _mineru_model_root() is not None


def load_table_parser(parser_config: MineruParserConfig) -> None:
    if not table_parser_available():
        raise ValueError("table parser is not installed")
    prepare_mineru_runtime_config()
    from mineru.backend.pipeline.pipeline_analyze import ModelSingleton

    ModelSingleton().get_model(lang="ch", formula_enable=parser_config.formula, table_enable=parser_config.table_enable)


def parse_document_blocks(
    filepath: str,
    filename: str,
    file_type: str,
    parser_config: MineruParserConfig | None = None,
    backend: str = "pipeline",
) -> list[Block]:
    if not table_parser_available():
        raise ValueError("table parser is not installed")

    with tempfile.TemporaryDirectory(prefix="mineru_") as output_dir:
        try:
            _mineru_do_parse(
                output_dir=output_dir,
                filepath=filepath,
                filename=filename,
                file_type=file_type,
                parser_config=parser_config,
                backend=backend,
            )
            blocks = read_content_list_blocks(Path(output_dir))
        finally:
            device.release_memory()

    if not blocks:
        raise ValueError(f"Empty file: {filename}")
    return blocks


def prepare_mineru_runtime_config() -> None:
    config_path = MINERU_DIR / "mineru.json"
    if not config_path.exists():
        raise ValueError("table parser config is not installed")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config.setdefault("models-dir", {})["pipeline"] = str(MINERU_DIR / "pipeline")
    config["model-source"] = "local"
    runtime_config_path = Path(tempfile.gettempdir()) / "mineru_runtime_config.json"
    runtime_config_path.write_text(json.dumps(config, ensure_ascii=False, indent=4), encoding="utf-8")
    os.environ["MINERU_TOOLS_CONFIG_JSON"] = str(runtime_config_path)


def _mineru_do_parse(output_dir: str, filepath: str, filename: str, parser_config: MineruParserConfig | None = None, file_type: str = "pdf", backend: str = "pipeline") -> None:
    from mineru.cli.common import do_parse, read_fn
    from mineru.utils.enum_class import MakeMode

    stem = Path(filename).stem
    file_bytes = read_fn(Path(filepath), file_type)
    do_parse(
        output_dir=output_dir,
        pdf_file_names=[stem],
        pdf_bytes_list=[file_bytes],
        p_lang_list=["ch"],
        backend=backend,
        parse_method="auto" if parser_config is None else parser_config.parse_method,
        formula_enable=True if parser_config is None else parser_config.formula,
        table_enable=True if parser_config is None else parser_config.table_enable,
        f_draw_layout_bbox=False,
        f_draw_span_bbox=False,
        f_dump_md=False,
        f_dump_middle_json=True,
        f_dump_model_output=False,
        f_dump_orig_pdf=False,
        f_dump_content_list=True,
        f_make_md_mode=MakeMode.MM_MD,
    )


def _mineru_model_root() -> Path | None:
    model_root = MINERU_DIR / "pipeline"
    return model_root if (model_root / "models").exists() else None
