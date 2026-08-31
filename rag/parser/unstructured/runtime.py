import importlib
import importlib.util
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
UNSTRUCTURED_DIR = PROJECT_ROOT / "models" / "unstructured"
UNSTRUCTURED_MODEL_CONFIG = UNSTRUCTURED_DIR / "yolox.json"
HF_CACHE_DIR = PROJECT_ROOT / "models" / "huggingface" / "hub"
TABLE_STRUCTURE_MODEL_CACHE = HF_CACHE_DIR / "models--microsoft--table-transformer-structure-recognition"


def prepare_unstructured_runtime_config() -> None:
    if HF_CACHE_DIR.exists():
        os.environ.setdefault("HF_HOME", str(HF_CACHE_DIR.parent))
        os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(HF_CACHE_DIR))
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        from huggingface_hub import constants
        from transformers.utils import hub

        constants.HF_HOME = str(HF_CACHE_DIR.parent)
        constants.HF_HUB_CACHE = str(HF_CACHE_DIR)
        constants.HF_HUB_OFFLINE = True
        hub._is_offline_mode = True
    if not UNSTRUCTURED_MODEL_CONFIG.exists():
        return
    os.environ.setdefault("UNSTRUCTURED_DEFAULT_MODEL_NAME", "yolox")
    os.environ.setdefault("UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH", str(UNSTRUCTURED_MODEL_CONFIG))


def load_unstructured_layout_model() -> None:
    try:
        get_model = importlib.import_module("unstructured_inference.models.base").get_model
    except ImportError as exc:
        raise RuntimeError("unstructured inference parser is not installed") from exc
    get_model()


def load_unstructured_table_model() -> None:
    try:
        tables = importlib.import_module("unstructured_inference.models.tables")
    except ImportError as exc:
        raise RuntimeError("unstructured inference parser is not installed") from exc
    configure_unstructured_table_model(tables)
    tables.load_agent()


def configure_unstructured_table_model(tables) -> None:
    table_model = local_hf_snapshot(TABLE_STRUCTURE_MODEL_CACHE)
    if table_model is not None:
        tables.DEFAULT_MODEL = str(table_model)


def local_hf_snapshot(cache_dir: Path) -> Path | None:
    snapshots_dir = cache_dir / "snapshots"
    ref = cache_dir / "refs" / "main"
    if ref.exists():
        snapshot = snapshots_dir / ref.read_text(encoding="utf-8").strip()
        if snapshot.exists():
            return snapshot
    if not snapshots_dir.exists():
        return None
    snapshots = sorted(path for path in snapshots_dir.iterdir() if path.is_dir())
    return snapshots[-1] if snapshots else None


def unstructured_available() -> bool:
    return importlib.util.find_spec("unstructured") is not None
