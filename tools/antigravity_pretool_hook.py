#!/usr/bin/env python3
"""Google Antigravity PreToolUse Guardrail Hook.

Zero-dependency Python standard library PreToolUse lifecycle hook for Google
Antigravity (`~/.gemini/config/hooks.json` or `.agents/hooks.json`). Uses
`decision: "allow"` / `"deny"` without `overwrite` so it remains compatible
across Antigravity IDE, Desktop App, ACP, and `agy` CLI.

Enforces:
- Invariant 4: Line-bounded `view_file` / `read_file` calls (<= 150 lines).
- Invariant 3: Blocks bare unredirected log/file dumps (`cat`, `Get-Content`,
  `type`) on large files and guides the agent to `scratch/<task>.log`
  Head-and-Tail inspection or line-bounded slices.

Environment overrides:
- TOKEN_OPTIMIZER_HOOK_BYPASS=1        Emergency bypass (always allow)
- TOKEN_OPTIMIZER_MAX_READ_LINES=150   Max allowed line chunk per read
- TOKEN_OPTIMIZER_MAX_READ_BYTES=12288 Byte cutoff for unbounded reads
"""

import json
import os
import re
import shlex
import sys
from pathlib import Path
from urllib.parse import unquote

DEFAULT_MAX_READ_LINES = 150
DEFAULT_MAX_READ_BYTES = 12288

BINARY_EXTENSIONS = {
    ".7z", ".aac", ".avi", ".bin", ".bmp", ".class", ".db", ".dll", ".doc",
    ".docx", ".dylib", ".exe", ".flac", ".gif", ".gz", ".ico", ".jar", ".jpeg",
    ".jpg", ".m4a", ".mkv", ".mov", ".mp3", ".mp4", ".ogg", ".otf", ".pdf",
    ".png", ".ppt", ".pptx", ".pyc", ".pyd", ".rar", ".so", ".sqlite", ".tar",
    ".tif", ".tiff", ".ttf", ".wasm", ".wav", ".webm", ".webp", ".woff",
    ".woff2", ".xls", ".xlsx", ".zip",
}

LINE_LIMIT_COMMAND_FLAGS = re.compile(
    r"(?:\||\s>>?\s|\bhead\b|\btail\b|Select-Object|-(?:First|Last|Head|Tail)\b)",
    re.IGNORECASE,
)

RAW_DUMP_CMD_RE = re.compile(
    r"^\s*(?:cat|Get-Content|gc|type)\s+(.+?)\s*$",
    re.IGNORECASE,
)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        val = int(raw)
        return val if val > 0 else default
    except ValueError:
        return default


def _clean_path(raw: str) -> str:
    if not raw or not isinstance(raw, str):
        return ""
    text = raw.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        try:
            decoded = json.loads(text)
            if isinstance(decoded, str) and not any(ord(c) < 32 for c in decoded):
                text = decoded
        except (json.JSONDecodeError, ValueError):
            pass
    text = text.strip().strip('"').strip("'")
    if text.startswith("file:///"):
        text = text[7:]
        # Handle Windows drive URIs like /C:/foo
        if len(text) >= 3 and text[0] == "/" and text[2] == ":":
            text = text[1:]
    elif text.startswith("file://"):
        text = text[7:]
    text = unquote(text)
    text = re.sub(r"#L\d+(?:-L?\d+)?$", "", text, flags=re.IGNORECASE)
    return text.strip()


def _first_present(mapping: dict, *keys: str):
    for key in keys:
        val = mapping.get(key)
        if val is not None:
            return val
    return None


def _parse_int(val):
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    try:
        return int(str(val).strip())
    except (TypeError, ValueError):
        return None


def _is_exempt_path(path_obj: Path) -> bool:
    if path_obj.suffix.lower() in BINARY_EXTENSIONS:
        return True
    normalized = path_obj.as_posix().lower()
    if "/upload/" in normalized:
        return True
    return False


def _count_lines_capped(path_obj: Path, cap: int) -> int:
    count = 0
    with open(path_obj, "rb") as f:
        for _ in f:
            count += 1
            if count > cap:
                return count
    return count


def _resolve_candidate_path(raw_path: str, payload: dict) -> Path | None:
    cleaned = _clean_path(raw_path)
    if not cleaned:
        return None
    candidate = Path(cleaned)
    if candidate.is_absolute():
        return candidate

    base_dirs = []
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        base_dirs.append(Path(cwd))
    workspaces = payload.get("workspacePaths") or payload.get("workspace_paths") or []
    if isinstance(workspaces, list):
        for ws in workspaces:
            if isinstance(ws, str) and ws.strip():
                base_dirs.append(Path(ws))
    base_dirs.append(Path.cwd())

    for base in base_dirs:
        joined = base / candidate
        if joined.exists():
            return joined
    return base_dirs[0] / candidate


def evaluate_tool_call(payload: dict) -> dict:
    """Evaluate a PreToolUse hook payload and return {'decision': 'allow'|'deny', ...}."""
    if os.environ.get("TOKEN_OPTIMIZER_HOOK_BYPASS", "").strip() == "1":
        return {"decision": "allow"}

    if not isinstance(payload, dict):
        return {"decision": "allow"}

    tool_call = payload.get("toolCall") or payload.get("tool_call") or {}
    if not isinstance(tool_call, dict):
        return {"decision": "allow"}

    tool_name = str(
        tool_call.get("name")
        or payload.get("tool_name")
        or payload.get("name")
        or ""
    ).strip()
    args = (
        tool_call.get("args")
        or tool_call.get("arguments")
        or payload.get("tool_input")
        or {}
    )
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    if not isinstance(args, dict):
        args = {}

    max_lines = _int_env("TOKEN_OPTIMIZER_MAX_READ_LINES", DEFAULT_MAX_READ_LINES)
    max_bytes = _int_env("TOKEN_OPTIMIZER_MAX_READ_BYTES", DEFAULT_MAX_READ_BYTES)

    # 1. Guard view_file / read_file (Invariant 4)
    if tool_name in {"view_file", "read_file"}:
        raw_path = (
            args.get("Path")
            or args.get("AbsolutePath")
            or args.get("TargetFile")
            or args.get("file_path")
            or args.get("path")
            or ""
        )
        path_obj = _resolve_candidate_path(str(raw_path), payload)
        if path_obj is None or not path_obj.is_file() or _is_exempt_path(path_obj):
            return {"decision": "allow"}

        start_line = _parse_int(_first_present(args, "StartLine", "startLine", "start_line"))
        end_line = _parse_int(_first_present(args, "EndLine", "endLine", "end_line"))

        # Explicit bounded range: enforce chunk size <= max_lines
        if start_line is not None and end_line is not None and end_line >= start_line:
            span = end_line - start_line + 1
            if span > max_lines:
                return {
                    "decision": "deny",
                    "reason": (
                        f"[token-optimizer Invariant 4] Requested {span} lines ({start_line}-{end_line}) of "
                        f"'{path_obj.name}', exceeding the {max_lines}-line chunk limit. "
                        f"Narrow StartLine/EndLine to <= {max_lines} lines (or set TOKEN_OPTIMIZER_HOOK_BYPASS=1)."
                    ),
                }
            return {"decision": "allow"}

        # Unbounded or open-ended read: check byte size & line count
        try:
            file_size = path_obj.stat().st_size
            line_count = _count_lines_capped(path_obj, max_lines)
        except OSError:
            return {"decision": "allow"}

        if file_size > max_bytes or line_count > max_lines:
            lines_desc = f">{max_lines}" if line_count > max_lines else str(line_count)
            return {
                "decision": "deny",
                "reason": (
                    f"[token-optimizer Invariant 4] Blocked unbounded read of '{path_obj.name}' "
                    f"({lines_desc} lines, {file_size:,} bytes; limit {max_lines} lines / {max_bytes:,} bytes). "
                    f"Use grep_search first and pass StartLine/EndLine <= {max_lines} lines."
                ),
            }
        return {"decision": "allow"}

    # 2. Guard bare run_command raw file dumps (Invariant 3)
    if tool_name == "run_command":
        cmd = str(args.get("CommandLine") or args.get("commandLine") or args.get("command") or "")
        if not cmd or LINE_LIMIT_COMMAND_FLAGS.search(cmd):
            return {"decision": "allow"}

        match = RAW_DUMP_CMD_RE.match(cmd)
        if not match:
            return {"decision": "allow"}

        arg_str = match.group(1)
        try:
            tokens = [t for t in shlex.split(arg_str, posix=(os.name != "nt")) if not t.startswith("-")]
        except ValueError:
            tokens = [t for t in arg_str.split() if not t.startswith("-")]

        if len(tokens) != 1:
            return {"decision": "allow"}

        path_obj = _resolve_candidate_path(tokens[0], payload)
        if path_obj is None or not path_obj.is_file() or _is_exempt_path(path_obj):
            return {"decision": "allow"}

        try:
            file_size = path_obj.stat().st_size
            line_count = _count_lines_capped(path_obj, max_lines)
        except OSError:
            return {"decision": "allow"}

        if file_size > max_bytes or line_count > max_lines:
            lines_desc = f">{max_lines}" if line_count > max_lines else str(line_count)
            return {
                "decision": "deny",
                "reason": (
                    f"[token-optimizer Invariant 3] Blocked raw terminal dump of '{path_obj.name}' "
                    f"({lines_desc} lines, {file_size:,} bytes). Use view_file with StartLine/EndLine <= {max_lines}, "
                    f"head/tail (5 head + 25 tail), or redirect large command output to scratch/<task>.log."
                ),
            }

    return {"decision": "allow"}


def main():
    try:
        if hasattr(sys.stdin, "buffer"):
            raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
        else:
            raw = sys.stdin.read()
        if raw.startswith("\ufeff"):
            raw = raw.lstrip("\ufeff")
        payload = json.loads(raw) if raw.strip() else {}
        decision = evaluate_tool_call(payload)
    except Exception:
        decision = {"decision": "allow"}

    sys.stdout.write(json.dumps(decision, separators=(",", ":")) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
