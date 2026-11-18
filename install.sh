#!/usr/bin/env bash
# Antigravity Token Optimizer - POSIX Automated Installer (Linux / macOS)
# Usage:
#   Local:   ./install.sh [--target <path>] [--dry-run]
#   Remote:  curl -fsSL https://raw.githubusercontent.com/xcalibur73/antigravity-token-optimizer/main/install.sh | bash

set -euo pipefail

DRY_RUN=false
TARGET_RULES_PATH=""

usage() {
  cat <<'EOF'
Usage: install.sh [OPTIONS]

Options:
  -t, --target <path>   Override target AGENTS.md path
  -n, --dry-run         Simulate installation without modifying disk
  -h, --help            Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--target)
      if [[ $# -lt 2 ]]; then
        echo "Error: --target requires a path argument." >&2
        exit 1
      fi
      TARGET_RULES_PATH="$2"
      shift 2
      ;;
    -n|--dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: Unknown option '$1'" >&2
      usage >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

TARGET="$TARGET_RULES_PATH"
if [[ -z "$TARGET" ]]; then
  if [[ -n "${ANTIGRAVITY_RULES_PATH:-}" ]]; then
    TARGET="$ANTIGRAVITY_RULES_PATH"
  elif [[ -n "${AGY_RULES_PATH:-}" ]]; then
    TARGET="$AGY_RULES_PATH"
  else
    TARGET="$HOME/.gemini/config/rules/AGENTS.md"
  fi
fi

TARGET_DIR="$(dirname "$TARGET")"

echo "=================================================="
echo "Antigravity Token Optimizer: Automated Installer"
echo "=================================================="
echo "Target configuration path: $TARGET"

load_rules() {
  if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/rules/AGENTS.md" ]]; then
    cat "$SCRIPT_DIR/rules/AGENTS.md"
    return 0
  fi
  if [[ -f "rules/AGENTS.md" ]]; then
    cat "rules/AGENTS.md"
    return 0
  fi
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "https://raw.githubusercontent.com/xcalibur73/antigravity-token-optimizer/main/rules/AGENTS.md"
    return 0
  fi
  echo "Error: Could not locate local rules/AGENTS.md and curl is unavailable." >&2
  return 1
}

locate_linter() {
  if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/tools/antigravity_prefix_linter.py" ]]; then
    echo "$SCRIPT_DIR/tools/antigravity_prefix_linter.py"
    return 0
  fi
  if [[ -f "tools/antigravity_prefix_linter.py" ]]; then
    echo "$(pwd)/tools/antigravity_prefix_linter.py"
    return 0
  fi
  return 1
}

RULES_CONTENT="$(load_rules)"

if [[ ! -d "$TARGET_DIR" ]]; then
  if $DRY_RUN; then
    echo "[DRY-RUN] Would create directory: $TARGET_DIR"
  else
    mkdir -p "$TARGET_DIR"
    echo "Created target directory: $TARGET_DIR"
  fi
fi

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

if [[ -f "$TARGET" ]]; then
  if grep -qE "Prompt Caching Engine and Strict Prefix Invariance|Google Antigravity Agent Constitution" "$TARGET"; then
    echo "Status: Target rules file already contains Antigravity Invariants."
    echo "Action: System is already optimized. Exiting cleanly without modification."
    if LINTER_PATH="$(locate_linter)" && [[ -n "$PYTHON_BIN" ]]; then
      echo "Running prefix linter audit..."
      "$PYTHON_BIN" "$LINTER_PATH" "$TARGET"
      echo "Verification result: PASSED (exit code 0)."
    fi
    echo "=================================================="
    exit 0
  fi

  TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
  BACKUP_PATH="${TARGET}.bak.${TIMESTAMP}"
  if [[ -e "$BACKUP_PATH" ]]; then
    BACKUP_PATH="${TARGET}.bak.${TIMESTAMP}_1"
  fi

  if $DRY_RUN; then
    echo "[DRY-RUN] Existing rules file detected. Would create backup copy: $BACKUP_PATH"
    echo "[DRY-RUN] Would append Antigravity Invariants to: $TARGET"
  else
    cp "$TARGET" "$BACKUP_PATH"
    echo "Non-destructive backup created: $BACKUP_PATH"
    {
      cat "$TARGET"
      printf '\n\n%s\n' "$RULES_CONTENT"
    } > "${TARGET}.tmp"
    mv "${TARGET}.tmp" "$TARGET"
    echo "Injected Antigravity Token Optimizer invariants into: $TARGET"
  fi
else
  if $DRY_RUN; then
    echo "[DRY-RUN] Target file does not exist. Would write new invariants to: $TARGET"
  else
    printf '%s\n' "$RULES_CONTENT" > "$TARGET"
    echo "Created rules file with Antigravity Token Optimizer invariants: $TARGET"
  fi
fi

if $DRY_RUN; then
  echo "[DRY-RUN] Dry run completed successfully. Zero changes committed."
  echo "=================================================="
  exit 0
fi

if LINTER_PATH="$(locate_linter)" && [[ -n "$PYTHON_BIN" ]]; then
  echo "Running prefix linter audit..."
  "$PYTHON_BIN" "$LINTER_PATH" "$TARGET"
  echo "Verification result: PASSED (exit code 0)."
else
  echo "Note: Python or local prefix linter not available; skipped linter verification."
fi

echo "Optimization complete: Antigravity Token Optimizer is active."
echo "=================================================="
