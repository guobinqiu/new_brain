#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="$ROOT_DIR/models"

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
  "$ROOT_DIR/backend/.venv/bin/modelscope" download "$repo" --local-dir "$dir"
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
  "$ROOT_DIR/backend/.venv/bin/python" - "$dir" <<'PY'
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
  MINERU_TOOLS_CONFIG_JSON="$dir/mineru.json" "$ROOT_DIR/backend/.venv/bin/mineru-models-download" -s modelscope -m pipeline
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
    all)
      download_dense
      download_reranker
      download_bge_m3
      download_reranker_m3
      download_reranker_large
      download_rapidocr
      download_mineru
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
  curl -LsSf https://astral.sh/uv/install.sh | sh
  (cd "$ROOT_DIR/backend" && uv pip install modelscope "mineru[core]")

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
