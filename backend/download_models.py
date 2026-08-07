"""下载项目所需的所有模型到本地 models/ 目录（独立于服务启动执行）。

用法:
    uv run python download_models.py

下载内容（来源: modelscope.cn）:
    1. AI-ModelScope/bge-base-zh-v1.5  → models/bge-base-zh-v1.5/   (dense 模型)
    2. BAAI/bge-reranker-base          → models/bge-reranker-base/  (重排模型)
    3. BAAI/bge-m3                     → models/bge-m3/             (BGE-M3)
    4. BAAI/bge-reranker-v2-m3         → models/bge-reranker-v2-m3/ (BGE-M3 重排)
    5. BAAI/bge-reranker-large         → models/bge-reranker-large/ (大模型重排)
    6. RapidOCR ONNX 模型              → models/rapidocr/           (OCR)
"""
from dataclasses import dataclass
import os
import shutil
import sys

from config import MODELS_DIR, DENSE_MODEL_DIR, RERANKER_MODEL_DIR, RAPIDOCR_MODEL_DIR

# RapidOCR 模型来源（modelscope 官方 RapidAI/RapidOCR 仓库）
RAPIDOCR_SOURCE = "RapidAI/RapidOCR"
RAPIDOCR_FILES = [
    "PP-OCRv6_det_small.onnx",
    "PP-OCRv6_rec_small.onnx",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
]

BGE_M3_MODEL_DIR = os.path.join(MODELS_DIR, "bge-m3")
RERANKER_M3_MODEL_DIR = os.path.join(MODELS_DIR, "bge-reranker-v2-m3")
RERANKER_LARGE_MODEL_DIR = os.path.join(MODELS_DIR, "bge-reranker-large")
BGE_M3_FILES = (
    "config.json",
    "config_sentence_transformers.json",
    "configuration.json",
    "modules.json",
    "sentence_bert_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "sentencepiece.bpe.model",
    "pytorch_model.bin",
    "sparse_linear.pt",
    "colbert_linear.pt",
    "1_Pooling/config.json",
)
RERANKER_LARGE_FILES = (
    "config.json",
    "configuration.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "sentencepiece.bpe.model",
    "model.safetensors",
)
RERANKER_M3_FILES = RERANKER_LARGE_FILES


@dataclass(frozen=True)
class ModelSpec:
    label: str
    source: str
    local_dir: str
    marker_files: tuple[str, ...]
    allow_patterns: tuple[str, ...] | None = None
    require_all_markers: bool = False


MODEL_SPECS = (
    ModelSpec(
        label="dense 模型",
        source="AI-ModelScope/bge-base-zh-v1.5",
        local_dir=DENSE_MODEL_DIR,
        marker_files=("pytorch_model.bin", "model.safetensors"),
    ),
    ModelSpec(
        label="重排模型",
        source="BAAI/bge-reranker-base",
        local_dir=RERANKER_MODEL_DIR,
        marker_files=("model.safetensors",),
    ),
    ModelSpec(
        label="BGE-M3 模型",
        source="BAAI/bge-m3",
        local_dir=BGE_M3_MODEL_DIR,
        marker_files=("pytorch_model.bin",),
        allow_patterns=BGE_M3_FILES,
    ),
    ModelSpec(
        label="BGE-M3 重排模型",
        source="BAAI/bge-reranker-v2-m3",
        local_dir=RERANKER_M3_MODEL_DIR,
        marker_files=("model.safetensors",),
        allow_patterns=RERANKER_M3_FILES,
    ),
    ModelSpec(
        label="大模型重排",
        source="BAAI/bge-reranker-large",
        local_dir=RERANKER_LARGE_MODEL_DIR,
        marker_files=("model.safetensors",),
        allow_patterns=RERANKER_LARGE_FILES,
    ),
    ModelSpec(
        label="RapidOCR 模型",
        source=RAPIDOCR_SOURCE,
        local_dir=RAPIDOCR_MODEL_DIR,
        marker_files=tuple(RAPIDOCR_FILES),
        allow_patterns=tuple(RAPIDOCR_FILES),
        require_all_markers=True,
    ),
)


def model_exists(spec: ModelSpec):
    checks = [os.path.exists(os.path.join(spec.local_dir, f)) for f in spec.marker_files]
    if spec.require_all_markers:
        return all(checks)
    return any(checks)


def download_model(spec: ModelSpec, index: int, total: int):
    print(f"[{index}/{total}] 下载{spec.label} {spec.source} → {spec.local_dir}")
    if model_exists(spec):
        print("      已存在，跳过")
        return
    os.makedirs(spec.local_dir, exist_ok=True)
    from modelscope import snapshot_download
    kwargs = {}
    if spec.allow_patterns:
        kwargs["allow_patterns"] = list(spec.allow_patterns)
    snapshot_download(spec.source, local_dir=spec.local_dir, **kwargs)
    print("      完成")


def download_dense():
    download_model(MODEL_SPECS[0], 1, len(MODEL_SPECS))


def download_reranker():
    download_model(MODEL_SPECS[1], 2, len(MODEL_SPECS))


def download_bge_m3():
    download_model(MODEL_SPECS[2], 3, len(MODEL_SPECS))


def download_reranker_m3():
    download_model(MODEL_SPECS[3], 4, len(MODEL_SPECS))


def download_reranker_large():
    download_model(MODEL_SPECS[4], 5, len(MODEL_SPECS))


def download_ocr():
    download_model(MODEL_SPECS[5], 6, len(MODEL_SPECS))


def main():
    print(f"开始下载模型到 {MODELS_DIR} ...")
    os.makedirs(MODELS_DIR, exist_ok=True)
    for fn in (download_dense, download_reranker, download_bge_m3, download_reranker_m3, download_reranker_large, download_ocr):
        try:
            fn()
        except Exception as e:
            print(f"  [失败] {fn.__name__}: {e}", file=sys.stderr)
    print("模型下载完成。现在可以启动服务（完全离线）。")


if __name__ == "__main__":
    main()
