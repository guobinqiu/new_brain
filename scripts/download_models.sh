#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="${MODELS_DIR:-$ROOT_DIR/models}"
MODELSCOPE_BIN="${MODELSCOPE_BIN:-$ROOT_DIR/backend/.venv/bin/modelscope}"
MINERU_DIR="$MODELS_DIR/mineru"
MINERU_PIPELINE_DIR="$MINERU_DIR/pipeline"
MINERU_TOOLS_CONFIG_JSON="${MINERU_TOOLS_CONFIG_JSON:-$MINERU_DIR/mineru.json}"

BGE_BASE_DIR="$MODELS_DIR/bge-base-zh-v1.5"
RERANKER_BASE_DIR="$MODELS_DIR/bge-reranker-base"
BGE_M3_DIR="$MODELS_DIR/bge-m3"
RERANKER_M3_DIR="$MODELS_DIR/bge-reranker-v2-m3"
RERANKER_LARGE_DIR="$MODELS_DIR/bge-reranker-large"
RAPIDOCR_DIR="$MODELS_DIR/rapidocr"
MINERU_MODEL_SOURCE="${MINERU_MODEL_SOURCE:-modelscope}"
MINERU_MODEL_TYPE="${MINERU_MODEL_TYPE:-pipeline}"
MINERU_MODELS_BIN="${MINERU_MODELS_BIN:-$ROOT_DIR/backend/.venv/bin/mineru-models-download}"

BGE_M3_FILES=(
  config.json
  config_sentence_transformers.json
  configuration.json
  modules.json
  sentence_bert_config.json
  special_tokens_map.json
  tokenizer.json
  tokenizer_config.json
  sentencepiece.bpe.model
  pytorch_model.bin
  sparse_linear.pt
  colbert_linear.pt
  1_Pooling/config.json
)

RERANKER_FILES=(
  config.json
  configuration.json
  special_tokens_map.json
  tokenizer.json
  tokenizer_config.json
  sentencepiece.bpe.model
  model.safetensors
)

RAPIDOCR_FILES=(
  PP-OCRv6_det_small.onnx
  PP-OCRv6_rec_small.onnx
  ch_ppocr_mobile_v2.0_cls_mobile.onnx
)

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
  MODELS_DIR            Target models directory. Default: ./models
  MODELSCOPE_BIN        ModelScope CLI path. Default: ./backend/.venv/bin/modelscope
  MINERU_TOOLS_CONFIG_JSON  MinerU runtime config. Default: ./models/mineru/mineru.json
  MINERU_MODELS_BIN    MinerU model downloader. Default: ./backend/.venv/bin/mineru-models-download
  MINERU_MODEL_SOURCE  MinerU model source. Default: modelscope
  MINERU_MODEL_TYPE    MinerU model group. Default: pipeline
EOF
}

has_any_marker() {
  local dir="$1"
  shift
  local marker
  for marker in "$@"; do
    [[ -e "$dir/$marker" ]] && return 0
  done
  return 1
}

has_all_markers() {
  local dir="$1"
  shift
  local marker
  for marker in "$@"; do
    [[ -e "$dir/$marker" ]] || return 1
  done
  return 0
}

download_snapshot() {
  local label="$1"
  local repo="$2"
  local dir="$3"
  shift 3
  local markers=("$@")

  echo "下载 $label: $repo -> $dir"
  if has_any_marker "$dir" "${markers[@]}"; then
    echo "  已存在，跳过"
    return
  fi

  mkdir -p "$dir"
  "$MODELSCOPE_BIN" download "$repo" --local-dir "$dir"
}

download_filtered() {
  local label="$1"
  local repo="$2"
  local dir="$3"
  local marker_mode="$4"
  shift 4
  local files=("$@")

  echo "下载 $label: $repo -> $dir"
  if [[ "$marker_mode" == "all" ]]; then
    if has_all_markers "$dir" "${files[@]}"; then
      echo "  已存在，跳过"
      return
    fi
  else
    if has_any_marker "$dir" "${files[@]}"; then
      echo "  已存在，跳过"
      return
    fi
  fi

  mkdir -p "$dir"
  "$MODELSCOPE_BIN" download "$repo" --local-dir "$dir" --include "${files[@]}"
}

download_dense() {
  download_snapshot "dense 模型" "AI-ModelScope/bge-base-zh-v1.5" "$BGE_BASE_DIR" pytorch_model.bin model.safetensors
}

download_reranker() {
  download_snapshot "重排模型" "BAAI/bge-reranker-base" "$RERANKER_BASE_DIR" model.safetensors
}

download_bge_m3() {
  download_filtered "BGE-M3 模型" "BAAI/bge-m3" "$BGE_M3_DIR" any "${BGE_M3_FILES[@]}"
}

download_reranker_m3() {
  download_filtered "BGE-M3 重排模型" "BAAI/bge-reranker-v2-m3" "$RERANKER_M3_DIR" any "${RERANKER_FILES[@]}"
}

download_reranker_large() {
  download_filtered "大模型重排" "BAAI/bge-reranker-large" "$RERANKER_LARGE_DIR" any "${RERANKER_FILES[@]}"
}

download_rapidocr() {
  download_filtered "RapidOCR 模型" "RapidAI/RapidOCR" "$RAPIDOCR_DIR" all "${RAPIDOCR_FILES[@]}"
}

download_mineru() {
  echo "下载 MinerU 模型: source=$MINERU_MODEL_SOURCE model=$MINERU_MODEL_TYPE"
  if [[ ! -x "$MINERU_MODELS_BIN" ]]; then
    echo "MinerU model downloader not found: $MINERU_MODELS_BIN" >&2
    echo "Install backend dependencies first, or set MINERU_MODELS_BIN=/path/to/mineru-models-download." >&2
    exit 1
  fi
  mkdir -p "$MINERU_DIR"
  "$MINERU_MODELS_BIN" -s "$MINERU_MODEL_SOURCE" -m "$MINERU_MODEL_TYPE"
  configure_mineru_paths
}

configure_mineru_paths() {
  "$ROOT_DIR/backend/.venv/bin/python" - "$MINERU_TOOLS_CONFIG_JSON" "$MINERU_PIPELINE_DIR" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
pipeline_path = Path(sys.argv[2])
data = json.loads(config_path.read_text(encoding="utf-8"))
source = Path(data["models-dir"]["pipeline"])
if not source.exists():
    raise SystemExit(f"MinerU pipeline model directory not found: {source}")
pipeline_path.parent.mkdir(parents=True, exist_ok=True)
if pipeline_path.exists():
    if pipeline_path.is_symlink():
        pipeline_path.unlink()
    elif not (pipeline_path / "models").exists():
        raise SystemExit(f"MinerU pipeline directory exists but is not a model directory: {pipeline_path}")
if not pipeline_path.exists():
    if source.resolve() == pipeline_path.resolve():
        pass
    else:
        source.rename(pipeline_path)
data["models-dir"]["pipeline"] = str(pipeline_path.absolute())
config_path.write_text(json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
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

  if [[ ! -x "$MODELSCOPE_BIN" ]]; then
    echo "ModelScope CLI not found: $MODELSCOPE_BIN" >&2
    echo "Install backend dependencies first, or set MODELSCOPE_BIN=/path/to/modelscope." >&2
    exit 1
  fi

  mkdir -p "$MODELS_DIR"
  export MINERU_TOOLS_CONFIG_JSON
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
