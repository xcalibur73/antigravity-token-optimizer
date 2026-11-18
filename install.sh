#!/usr/bin/env bash
# Antigravity Token Optimizer - POSIX Automated Installer (Linux / macOS)
# Usage:
#   Local:   ./install.sh [--target <path>] [--with-hooks] [--dry-run]
#   Remote:  curl -fsSL https://raw.githubusercontent.com/xcalibur73/antigravity-token-optimizer/main/install.sh | bash

set -euo pipefail

DRY_RUN=false
WITH_HOOKS=false
TARGET_RULES_PATH=""
TARGET_HOOKS_PATH=""

usage() {
  cat <<'EOF'
Usage: install.sh [OPTIONS]

Options:
  -t, --target <path>        Override target AGENTS.md path (default: $HOME/.gemini/config/AGENTS.md)
      --with-hooks           Install and register PreToolUse guardrail hook in $HOME/.gemini/config/hooks.json
      --hooks-target <path>  Override target hooks.json path
  -n, --dry-run              Simulate installation without modifying disk
  -h, --help                 Show this help message
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
    --with-hooks)
      WITH_HOOKS=true
      shift
      ;;
    --hooks-target)
      if [[ $# -lt 2 ]]; then
        echo "Error: --hooks-target requires a path argument." >&2
        exit 1
      fi
      TARGET_HOOKS_PATH="$2"
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
    TARGET="$HOME/.gemini/config/AGENTS.md"
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

load_hook_script() {
  if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/tools/antigravity_pretool_hook.py" ]]; then
    cat "$SCRIPT_DIR/tools/antigravity_pretool_hook.py"
    return 0
  fi
  if [[ -f "tools/antigravity_pretool_hook.py" ]]; then
    cat "tools/antigravity_pretool_hook.py"
    return 0
  fi
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "https://raw.githubusercontent.com/xcalibur73/antigravity-token-optimizer/main/tools/antigravity_pretool_hook.py"
    return 0
  fi
  echo "Error: Could not locate tools/antigravity_pretool_hook.py and curl is unavailable." >&2
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
    echo "Action: Rules file already optimized."
  else
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
  fi
else
  if $DRY_RUN; then
    echo "[DRY-RUN] Target file does not exist. Would write new invariants to: $TARGET"
  else
    printf '%s\n' "$RULES_CONTENT" > "$TARGET"
    echo "Created rules file with Antigravity Token Optimizer invariants: $TARGET"
  fi
fi

if $WITH_HOOKS; then
  HOOKS_JSON="${TARGET_HOOKS_PATH:-${ANTIGRAVITY_HOOKS_PATH:-$HOME/.gemini/config/hooks.json}}"
  HOOKS_DIR="$(dirname "$HOOKS_JSON")"
  HOOK_DEST="$HOOKS_DIR/tools/antigravity_pretool_hook.py"

  if $DRY_RUN; then
    echo "[DRY-RUN] Would install PreToolUse hook script to: $HOOK_DEST"
    echo "[DRY-RUN] Would register 'token-optimizer' PreToolUse hook in: $HOOKS_JSON"
  else
    if [[ -z "$PYTHON_BIN" ]]; then
      echo "Error: --with-hooks requires python3 or python to safely update hooks.json." >&2
      exit 1
    fi
    HOOK_CONTENT="$(load_hook_script)"
    mkdir -p "$(dirname "$HOOK_DEST")"
    printf '%s\n' "$HOOK_CONTENT" > "$HOOK_DEST"
    chmod +x "$HOOK_DEST"
    echo "Installed PreToolUse hook script: $HOOK_DEST"

    if [[ -f "$HOOKS_JSON" ]]; then
      HOOK_BAK="${HOOKS_JSON}.bak.$(date +%Y%m%d_%H%M%S)"
      cp "$HOOKS_JSON" "$HOOK_BAK"
      echo "Non-destructive hooks backup created: $HOOK_BAK"
    fi

    "$PYTHON_BIN" - "$HOOKS_JSON" "$HOOK_DEST" "$PYTHON_BIN" <<'PY'
import json
import sys
from pathlib import Path

hooks_path = Path(sys.argv[1])
hook_script = sys.argv[2]
python_bin = sys.argv[3]

data = {}
if hooks_path.is_file():
    raw = hooks_path.read_text(encoding="utf-8").strip()
    if raw:
        data = json.loads(raw)

if not isinstance(data, dict):
    raise SystemExit(f"Expected JSON object in {hooks_path}")

data["token-optimizer"] = {
    "enabled": True,
    "PreToolUse": [
        {
            "matcher": "view_file|read_file|run_command",
            "hooks": [
                {
                    "type": "command",
                    "command": f'{python_bin} "{hook_script}"',
                    "timeout": 10,
                }
            ],
        }
    ],
}

hooks_path.parent.mkdir(parents=True, exist_ok=True)
hooks_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
    echo "Registered PreToolUse guardrail hook in: $HOOKS_JSON"
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
