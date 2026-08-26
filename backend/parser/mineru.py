import importlib.util
import os
import tempfile
from pathlib import Path

from parser.schema import Block
from parser.table_transform import read_table_blocks, read_table_documents
from parser.validation import validate_pdf_file
from schema import ParserConfig


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MINERU_DIR = PROJECT_ROOT / "models" / "mineru"


def table_parser_available() -> bool:
    return importlib.util.find_spec("mineru") is not None and _mineru_model_root() is not None


def load_table_parser() -> None:
    if not table_parser_available():
        raise ValueError("table parser is not installed")
    _prepare_mineru_runtime_config()
    from mineru.backend.pipeline.pipeline_analyze import ModelSingleton

    ModelSingleton().get_model(lang="ch", formula_enable=True, table_enable=True)


def parse_pdf_table(filepath: str, filename: str, parser_config: ParserConfig) -> list[dict]:
    if not table_parser_available():
        raise ValueError("table parser is not installed")
    validate_pdf_file(filepath)

    with tempfile.TemporaryDirectory(prefix="mineru_") as output_dir:
        _mineru_do_parse(
            output_dir=output_dir,
            filepath=filepath,
            filename=filename,
        )
        chunks = read_table_documents(Path(output_dir), filename, parser_config)

    if not chunks:
        raise ValueError(f"Empty file: {filename}")
    return chunks


def parse_document_blocks(filepath: str, filename: str, file_type: str, parser_config: ParserConfig) -> list[Block]:
    if not table_parser_available():
        raise ValueError("table parser is not installed")

    with tempfile.TemporaryDirectory(prefix="mineru_") as output_dir:
        _mineru_do_parse(
            output_dir=output_dir,
            filepath=filepath,
            filename=filename,
            file_type=file_type,
        )
        blocks = read_table_blocks(Path(output_dir), parser_config)

    if not blocks:
        raise ValueError(f"Empty file: {filename}")
    return blocks


def _prepare_mineru_runtime_config() -> None:
    config_path = MINERU_DIR / "mineru.json"
    if not config_path.exists():
        raise ValueError("table parser config is not installed")
    os.environ["MINERU_TOOLS_CONFIG_JSON"] = str(config_path)


def _mineru_do_parse(output_dir: str, filepath: str, filename: str, file_type: str = "pdf") -> None:
    from mineru.cli.common import do_parse, read_fn
    from mineru.utils.enum_class import MakeMode

    stem = Path(filename).stem
    file_bytes = read_fn(Path(filepath), file_type)
    do_parse(
        output_dir=output_dir,
        pdf_file_names=[stem],
        pdf_bytes_list=[file_bytes],
        p_lang_list=["ch"],
        backend="pipeline",
        parse_method="auto",
        formula_enable=True,
        table_enable=True,
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
