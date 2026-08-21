#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="${MODELS_DIR:-$ROOT_DIR/models}"
MODELSCOPE_BIN="${MODELSCOPE_BIN:-$ROOT_DIR/backend/.venv/bin/modelscope}"

BGE_BASE_DIR="$MODELS_DIR/bge-base-zh-v1.5"
RERANKER_BASE_DIR="$MODELS_DIR/bge-reranker-base"
BGE_M3_DIR="$MODELS_DIR/bge-m3"
RERANKER_M3_DIR="$MODELS_DIR/bge-reranker-v2-m3"
RERANKER_LARGE_DIR="$MODELS_DIR/bge-reranker-large"
RAPIDOCR_DIR="$MODELS_DIR/rapidocr"

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
  all

Environment:
  MODELS_DIR       Target models directory. Default: ./models
  MODELSCOPE_BIN  ModelScope CLI path. Default: ./backend/.venv/bin/modelscope
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
    all)
      download_dense
      download_reranker
      download_bge_m3
      download_reranker_m3
      download_reranker_large
      download_rapidocr
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
