import importlib.util
import json
import os
import tempfile
import uuid
from pathlib import Path

from parser.table_transform import read_table_chunks
from schema import ParserConfig


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MINERU_CONFIG_JSON = PROJECT_ROOT / "models" / "mineru" / "mineru.json"


def table_parser_available() -> bool:
    return importlib.util.find_spec("mineru") is not None and _mineru_model_root() is not None


def load_table_parser() -> None:
    if not table_parser_available():
        raise ValueError("table parser is not installed")
    _set_mineru_runtime_env()
    from mineru.backend.pipeline.pipeline_analyze import ModelSingleton

    ModelSingleton().get_model(lang="ch", formula_enable=True, table_enable=True)


def parse_pdf_table(filepath: str, filename: str, parser_config: ParserConfig) -> list[dict]:
    if not table_parser_available():
        raise ValueError("table parser is not installed")

    with tempfile.TemporaryDirectory(prefix="mineru_") as output_dir:
        _set_mineru_runtime_env()
        _mineru_do_parse(
            output_dir=output_dir,
            filepath=filepath,
            filename=filename,
        )
        contents = read_table_chunks(Path(output_dir), parser_config)

    chunks = []
    for chunk_index, content in enumerate(contents):
        content = content.strip()
        if not content:
            continue
        chunks.append({
            "content": content,
            "metadata": {
                "filename": filename,
                "chunk_index": chunk_index,
            },
            "id": str(uuid.uuid4()),
        })
    if not chunks:
        raise ValueError(f"Empty file: {filename}")
    return chunks


def _set_mineru_config_env() -> None:
    os.environ["MINERU_TOOLS_CONFIG_JSON"] = str(MINERU_CONFIG_JSON)


def _set_mineru_runtime_env() -> None:
    _set_mineru_config_env()


def _mineru_do_parse(output_dir: str, filepath: str, filename: str) -> None:
    from mineru.cli.common import do_parse, read_fn
    from mineru.utils.enum_class import MakeMode

    stem = Path(filename).stem
    pdf_bytes = read_fn(Path(filepath), "pdf")
    do_parse(
        output_dir=output_dir,
        pdf_file_names=[stem],
        pdf_bytes_list=[pdf_bytes],
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
    if not MINERU_CONFIG_JSON.exists():
        return None
    try:
        config = json.loads(MINERU_CONFIG_JSON.read_text(encoding="utf-8"))
        pipeline = config["models-dir"]["pipeline"]
    except Exception:
        return None
    path = Path(pipeline).expanduser()
    if not path.is_absolute():
        path = MINERU_CONFIG_JSON.parent / path
    return path if path.exists() else None
