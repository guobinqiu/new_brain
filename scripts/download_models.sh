#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="$ROOT_DIR/models"
RAG_VENV="${RAG_VENV:-$ROOT_DIR/rag/.venv}"

usage() {
  cat <<'EOF'
Usage:
  scripts/download_models.sh [model ...]

Models:
  dense
  reranker
  bge-m3
  reranker-m3
  reranker-large
  rapidocr
  mineru
  unstructured
  all

Environment:
  Models are downloaded to ./models.
EOF
}

download_snapshot() {
  local label="$1"
  local repo="$2"
  local dir="$MODELS_DIR/$repo"

  echo "下载 $label: $repo -> $dir"
  if [[ -d "$dir" && -n "$(find "$dir" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    echo "  已存在，跳过"
    return
  fi

  mkdir -p "$dir"
  "$RAG_VENV/bin/modelscope" download "$repo" --local-dir "$dir"
}

download_dense() {
  download_snapshot "dense 模型" "AI-ModelScope/bge-base-zh-v1.5"
}

download_reranker() {
  download_snapshot "重排模型" "BAAI/bge-reranker-base"
}

download_bge_m3() {
  download_snapshot "BGE-M3 模型" "BAAI/bge-m3"
}

download_reranker_m3() {
  download_snapshot "BGE-M3 重排模型" "BAAI/bge-reranker-v2-m3"
}

download_reranker_large() {
  download_snapshot "大模型重排" "BAAI/bge-reranker-large"
}

download_rapidocr() {
  download_snapshot "RapidOCR 模型" "RapidAI/RapidOCR"
}

download_mineru() {
  local dir="$MODELS_DIR/mineru"
  echo "下载 MinerU 模型: pipeline -> $dir/pipeline"
  mkdir -p "$dir"
  "$RAG_VENV/bin/python" - "$dir" <<'PY'
import json
import sys
from pathlib import Path

mineru_dir = Path(sys.argv[1])
config = {
    "models-dir": {
        "pipeline": str(mineru_dir / "pipeline"),
        "vlm": "",
    },
    "model-source": "local",
}
(mineru_dir / "mineru.json").write_text(json.dumps(config, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
PY
  MINERU_TOOLS_CONFIG_JSON="$dir/mineru.json" "$RAG_VENV/bin/mineru-models-download" -s modelscope -m pipeline
}

download_unstructured() {
  local dir="$MODELS_DIR/unstructured"
  local hf_dir="$MODELS_DIR/huggingface"
  local layout_model="$dir/yolox_l0.05.onnx"
  local model_config="$dir/yolox.json"

  echo "下载 Unstructured 模型: yolox -> $dir"
  mkdir -p "$dir"

  "$RAG_VENV/bin/python" -m spacy download en_core_web_sm

  HF_HOME="$hf_dir" \
  HUGGINGFACE_HUB_CACHE="$hf_dir/hub" \
  "$RAG_VENV/bin/python" - "$layout_model" "$model_config" <<'PY'
import json
import shutil
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download

layout_model = Path(sys.argv[1])
model_config = Path(sys.argv[2])
source = hf_hub_download("unstructuredio/yolo_x_layout", "yolox_l0.05.onnx")
if Path(source).resolve() != layout_model.resolve():
    shutil.copyfile(source, layout_model)
snapshot_download("microsoft/table-transformer-structure-recognition")
snapshot_download("timm/resnet18.a1_in1k")
config = {
    "model_path": str(layout_model),
    "label_map": {
        "0": "Caption",
        "1": "Footnote",
        "2": "Formula",
        "3": "List-item",
        "4": "Page-footer",
        "5": "Page-header",
        "6": "Picture",
        "7": "Section-header",
        "8": "Table",
        "9": "Text",
        "10": "Title",
    },
}
model_config.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"  layout model: {layout_model}")
print(f"  model config: {model_config}")
PY
}

download_one() {
  case "$1" in
    dense)
      download_dense
      ;;
    reranker)
      download_reranker
      ;;
    bge-m3)
      download_bge_m3
      ;;
    reranker-m3)
      download_reranker_m3
      ;;
    reranker-large)
      download_reranker_large
      ;;
    rapidocr)
      download_rapidocr
      ;;
    mineru)
      download_mineru
      ;;
    unstructured)
      download_unstructured
      ;;
    all)
      download_dense
      download_reranker
      download_bge_m3
      download_reranker_m3
      download_reranker_large
      download_rapidocr
      download_mineru
      download_unstructured
      ;;
    *)
      echo "Unknown model: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
}

main() {
  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    return
  fi

  echo "安装模型下载工具"
  curl -LsSf https://astral.sh/uv/install.sh | sh && source "$HOME/.local/bin/env"
  if [[ ! -x "$RAG_VENV/bin/python" ]]; then
    (cd "$ROOT_DIR/rag" && uv venv .venv)
  fi
  if [[ ! -x "$RAG_VENV/bin/modelscope" || ! -x "$RAG_VENV/bin/mineru-models-download" ]]; then
    UV_PROJECT_ENVIRONMENT="$RAG_VENV" uv pip install modelscope "mineru[core]" "unstructured[all-docs]>=0.18.0"
  fi

  mkdir -p "$MODELS_DIR"
  echo "模型目录: $MODELS_DIR"

  if [[ "$#" -eq 0 ]]; then
    download_one all
    return
  fi

  local model
  for model in "$@"; do
    download_one "$model"
  done
}

main "$@"
