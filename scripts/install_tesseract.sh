#!/usr/bin/env bash
set -euo pipefail

has_command() {
  command -v "$1" >/dev/null 2>&1
}

print_langs() {
  echo
  echo "Installed Tesseract languages:"
  tesseract --list-langs || true
}

install_macos() {
  if ! has_command brew; then
    echo "Homebrew is required on macOS: https://brew.sh/" >&2
    exit 1
  fi

  brew install tesseract tesseract-lang
}

install_debian() {
  sudo apt-get update
  sudo apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim
}

install_rhel() {
  local installer="$1"
  sudo "$installer" install -y tesseract tesseract-langpack-eng tesseract-langpack-chi_sim
}

install_linux() {
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
  else
    echo "Cannot detect Linux distribution: /etc/os-release not found" >&2
    exit 1
  fi

  case "${ID:-}" in
    ubuntu|debian)
      install_debian
      ;;
    rhel|centos|fedora|rocky|almalinux)
      if has_command dnf; then
        install_rhel dnf
      elif has_command yum; then
        install_rhel yum
      else
        echo "dnf or yum is required on ${ID}" >&2
        exit 1
      fi
      ;;
    *)
      echo "Unsupported Linux distribution: ${ID:-unknown}" >&2
      echo "Install packages manually: tesseract, English language pack, Simplified Chinese language pack." >&2
      exit 1
      ;;
  esac
}

main() {
  case "$(uname -s)" in
    Darwin)
      install_macos
      ;;
    Linux)
      install_linux
      ;;
    *)
      echo "Unsupported OS: $(uname -s)" >&2
      exit 1
      ;;
  esac

  echo
  echo "Tesseract version:"
  tesseract --version
  print_langs

  if ! tesseract --list-langs 2>/dev/null | grep -qx "chi_sim"; then
    echo
    echo "Warning: chi_sim language pack was not found after installation." >&2
    exit 1
  fi
}

main "$@"
