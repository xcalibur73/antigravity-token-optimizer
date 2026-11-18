#!/usr/bin/env python3
"""Google Antigravity Prefix Linter.

Audits Antigravity rules files, prompt configurations, tool schemas, and template
headers for dynamic variables (timestamps, UUIDs, nonces, session identifiers),
unsorted tool schemas or schema keys, and in-place prompt mutation patterns that
invalidate Google Gemini KV cache prefix hashing.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

TAIL_MARKER_PATTERN = re.compile(
    r"(?:<!--\s*(?:DYNAMIC_TAIL|USER_TURN_TAIL)\s*-->|#\s*DYNAMIC_TAIL\b)",
    re.IGNORECASE,
)

INLINE_IGNORE_PATTERN = re.compile(
    r"(?:#|//|<!--)\s*prefix-linter:\s*ignore\b",
    re.IGNORECASE,
)

LINT_RULES = [
    {
        "id": "DYNAMIC_INTERPOLATION",
        "description": "Dynamic template interpolation in prompt prefix",
        "regex": re.compile(
            r"{{\s*(?:timestamp|date|time|now|uuid|session_id|request_id|nonce)\s*}}",
            re.IGNORECASE,
        ),
        "severity": "ERROR",
        "fix": "Move dynamic variables from system prompt prefix to the tail of user turns.",
    },
    {
        "id": "DYNAMIC_DATE_CALL",
        "description": "Dynamic date generation call in prefix scope",
        "regex": re.compile(r"\b(?:datetime\.now|Date\.now|time\.time|uuid\.uuid4)\(\)"),
        "severity": "ERROR",
        "fix": "Pin static system rules; avoid dynamic time invocation in prompt prefixes.",
    },
    {
        "id": "LITERAL_ISO_TIMESTAMP",
        "description": "Literal ISO 8601 timestamp in prefix header",
        "regex": re.compile(
            r"\b202[0-9]-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9](?:\.\d+)?(?:Z|[+-][0-2][0-9]:?[0-5][0-9])?\b"
        ),
        "severity": "ERROR",
        "fix": "Remove dynamic timestamps from static prefixes. Relocate to user turn footer.",
    },
    {
        "id": "LITERAL_UUID",
        "description": "Literal UUID found in prefix content",
        "regex": re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
        "severity": "WARNING",
        "fix": "Use static identifiers in prompt templates. Place ephemeral UUIDs at user message tail.",
    },
    {
        "id": "DYNAMIC_SESSION_ASSIGNMENT",
        "description": "Dynamic session or request parameter in prefix",
        "regex": re.compile(
            r"(?:session_id|request_id|turn_nonce|client_nonce)\s*=\s*['\"][^'\"]+['\"]",
            re.IGNORECASE,
        ),
        "severity": "ERROR",
        "fix": "Prefix headers must remain identical across sessions for KV cache reuse.",
    },
    {
        "id": "IN_PLACE_PROMPT_MUTATION",
        "description": "In-place system prompt or conversation history mutation pattern detected",
        "regex": re.compile(
            r"(?:(?<!def\s)\b(?:set_system_prompt|update_system_prompt|replace_system_prompt|modify_system_prompt|mutate_system_prompt|reset_system_prompt|replace_system_message)\s*\("
            r"|(?:\.system_prompt|\.system_instruction)\s*=(?!=)"
            r"|\b(?:messages|history|conversation)\[0\](?:\s*\[['\"][^'\"]+['\"]\])?\s*=(?!=)"
            r"|\b(?:system_prompt|system_instruction)\.(?:replace|format|update)\s*\()",
            re.IGNORECASE,
        ),
        "severity": "ERROR",
        "fix": "Never mutate system prompts or prior turns in place. Append runtime state updates to conversation tail.",
    },
]


def _find_line_for_token(lines, token, start_line=1):
    """Locate the first line number (>= start_line) containing token."""
    for idx, line in enumerate(lines[start_line - 1:], start=start_line):
        if token in line:
            return idx
    return start_line


def _extract_balanced_bracket_blocks(text):
    """Extract balanced `[...]` blocks preceded by tools/function_declarations/functions assignment."""
    header_re = re.compile(
        r"\b(?:tools|function_declarations|functions)\s*(?:=|:)\s*\[",
        re.IGNORECASE,
    )
    blocks = []
    for match in header_re.finditer(text):
        open_idx = match.end() - 1
        depth = 0
        in_string = None
        escaped = False
        end_idx = None

        for pos in range(open_idx, len(text)):
            ch = text[pos]
            if escaped:
                escaped = False
                continue
            if ch == "\\" and in_string is not None:
                escaped = True
                continue
            if in_string is not None:
                if ch == in_string:
                    in_string = None
                continue
            if ch in ('"', "'"):
                in_string = ch
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end_idx = pos
                    break

        if end_idx is not None:
            blocks.append((match.start(), text[open_idx + 1 : end_idx], text[match.start() : end_idx + 1]))
    return blocks


def _check_json_dict_key_ordering(node, file_path, lines, violations, is_schema_context=False):
    """Recursively verify alphabetical key ordering inside tool schema objects."""
    if isinstance(node, dict):
        keys = list(node.keys())
        schema_context = is_schema_context or any(
            k in node for k in ("tools", "function_declarations", "functions", "inputSchema", "parameters", "properties")
        )
        if schema_context and len(keys) >= 2:
            sorted_keys = sorted(keys)
            if keys != sorted_keys:
                for i in range(len(keys) - 1):
                    if keys[i] > keys[i + 1]:
                        line_no = _find_line_for_token(lines, f'"{keys[i + 1]}"')
                        violations.append({
                            "file": str(file_path),
                            "line": line_no,
                            "rule": "UNSORTED_SCHEMA_KEYS",
                            "matched": f"{keys[i]} before {keys[i + 1]}",
                            "line_text": lines[line_no - 1].strip()[:120] if line_no <= len(lines) else "",
                            "message": f"Schema object keys must be sorted alphabetically. Found '{keys[i]}' before '{keys[i + 1]}'.",
                            "severity": "ERROR",
                            "fix": "Run tools/mcp_schema_compressor.py to sort schema keys and tool declarations deterministically.",
                        })
                        break
        for k, v in node.items():
            if k == "required" and isinstance(v, list) and all(isinstance(x, str) for x in v) and len(v) >= 2:
                if v != sorted(v):
                    for i in range(len(v) - 1):
                        if v[i] > v[i + 1]:
                            line_no = _find_line_for_token(lines, f'"{v[i + 1]}"')
                            violations.append({
                                "file": str(file_path),
                                "line": line_no,
                                "rule": "UNSORTED_SCHEMA_KEYS",
                                "matched": f"{v[i]} before {v[i + 1]}",
                                "line_text": lines[line_no - 1].strip()[:120] if line_no <= len(lines) else "",
                                "message": f"Required parameter array must be sorted alphabetically. Found '{v[i]}' before '{v[i + 1]}'.",
                                "severity": "ERROR",
                                "fix": "Sort required parameter arrays alphabetically.",
                            })
                            break
            _check_json_dict_key_ordering(v, file_path, lines, violations, is_schema_context=schema_context)
    elif isinstance(node, list):
        for item in node:
            _check_json_dict_key_ordering(item, file_path, lines, violations, is_schema_context=is_schema_context)


def check_tool_ordering(file_path, lines, text):
    """Scan file content for unsorted tool declarations or tool schemas."""
    violations = []
    path_obj = Path(file_path)

    # 1. Direct JSON check for tool arrays and schema key ordering
    if path_obj.suffix.lower() == ".json":
        try:
            data = json.loads(text)
            tool_lists = []
            if isinstance(data, dict):
                for k in ["tools", "function_declarations", "functions"]:
                    if k in data and isinstance(data[k], list):
                        tool_lists.append(data[k])
            elif isinstance(data, list):
                tool_lists.append(data)

            for t_list in tool_lists:
                names = []
                for item in t_list:
                    if isinstance(item, dict):
                        name = (
                            item.get("name")
                            or (item.get("function", {}).get("name") if isinstance(item.get("function"), dict) else None)
                            or (item.get("tool", {}).get("name") if isinstance(item.get("tool"), dict) else None)
                        )
                        if name:
                            names.append(str(name))
                    elif isinstance(item, str):
                        names.append(item)

                if len(names) >= 2:
                    for i in range(len(names) - 1):
                        if (names[i].lower(), names[i]) > (names[i + 1].lower(), names[i + 1]):
                            offending_line = _find_line_for_token(lines, names[i + 1])
                            violations.append({
                                "file": str(file_path),
                                "line": offending_line,
                                "rule": "UNSORTED_TOOL_DEFINITIONS",
                                "matched": f"{names[i]} before {names[i + 1]}",
                                "line_text": lines[offending_line - 1].strip()[:120],
                                "message": f"Tool definitions must be sorted alphabetically by identifier name. Found '{names[i]}' before '{names[i + 1]}'.",
                                "severity": "ERROR",
                                "fix": "Sort tool schemas, function declarations, and parameter definitions alphabetically prior to registration.",
                            })
                            break

            # Enforce nested schema key & required array sorting on tool schema JSON files
            if tool_lists or (isinstance(data, dict) and ("inputSchema" in data or "properties" in data)):
                _check_json_dict_key_ordering(data, file_path, lines, violations)
            return violations
        except Exception:
            pass

    # 2. Balanced bracket check for code blocks, Python, Markdown: tools = [ ... ]
    for start_char, block_content, full_match in _extract_balanced_bracket_blocks(text):
        if path_obj.suffix.lower() == ".py" and ("re.compile" in full_match or "pattern" in full_match):
            continue

        names = []
        name_dict_matches = re.findall(r"['\"]name['\"]\s*:\s*['\"]([^'\"]+)['\"]", block_content)
        if name_dict_matches:
            names = name_dict_matches
        else:
            str_matches = re.findall(r"['\"]([a-zA-Z0-9_-]+)['\"]", block_content)
            if str_matches:
                names = str_matches
            else:
                ident_matches = re.findall(r"\b([a-zA-Z0-9_]+)\b", block_content)
                names = [
                    m for m in ident_matches
                    if m not in {"tools", "function_declarations", "functions", "None", "True", "False"}
                ]

        if len(names) >= 2:
            for i in range(len(names) - 1):
                if (names[i].lower(), names[i]) > (names[i + 1].lower(), names[i + 1]):
                    line_no = text[:start_char].count("\n") + 1
                    line_no = _find_line_for_token(lines, names[i + 1], start_line=line_no)
                    violations.append({
                        "file": str(file_path),
                        "line": line_no,
                        "rule": "UNSORTED_TOOL_DEFINITIONS",
                        "matched": f"{names[i]} before {names[i + 1]}",
                        "line_text": lines[line_no - 1].strip()[:120] if line_no <= len(lines) else "",
                        "message": f"Tool definitions must be sorted alphabetically by identifier name. Found '{names[i]}' before '{names[i + 1]}'.",
                        "severity": "ERROR",
                        "fix": "Sort tool schemas, function declarations, and parameter definitions alphabetically prior to registration.",
                    })
                    break

    # 3. YAML list pattern
    yaml_tool_pattern = re.compile(
        r"^(?:tools|function_declarations|functions)\s*:\s*\n((?:\s*-\s+.*?\n)+)",
        re.IGNORECASE | re.MULTILINE,
    )
    for match in yaml_tool_pattern.finditer(text):
        yaml_block = match.group(1)
        names = re.findall(r"-\s+(?:name:\s*)?['\"]?([a-zA-Z0-9_-]+)['\"]?", yaml_block)
        if len(names) >= 2:
            for i in range(len(names) - 1):
                if (names[i].lower(), names[i]) > (names[i + 1].lower(), names[i + 1]):
                    line_no = text[:match.start()].count("\n") + 1
                    violations.append({
                        "file": str(file_path),
                        "line": line_no,
                        "rule": "UNSORTED_TOOL_DEFINITIONS",
                        "matched": f"{names[i]} before {names[i + 1]}",
                        "line_text": lines[line_no - 1].strip()[:120] if line_no <= len(lines) else "",
                        "message": f"Tool definitions must be sorted alphabetically by identifier name. Found '{names[i]}' before '{names[i + 1]}'.",
                        "severity": "ERROR",
                        "fix": "Sort tool schemas, function declarations, and parameter definitions alphabetically prior to registration.",
                    })
                    break

    return violations


VALID_RULE_TRIGGERS = {"always_on", "model_decision", "glob", "manual"}
FORBIDDEN_PLUGIN_DISPLAY_PREFIXES = ("antigravity", "gemini", "claude", "cursor")
ANTIGRAVITY_RULE_MAX_BYTES = 24000
ANTIGRAVITY_RULES_TOKEN_BUDGET = 20000


def _parse_yaml_frontmatter(text):
    """Extract leading YAML frontmatter block if present."""
    match = re.match(r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.DOTALL)
    if not match:
        return None
    return match.group(1)


def _is_antigravity_rule_file(path_obj: Path) -> bool:
    """Identify Antigravity instruction/rule markdown files."""
    if path_obj.suffix.lower() != ".md":
        return False
    name_upper = path_obj.name.upper()
    parent_name = path_obj.parent.name.lower()
    return name_upper in {"AGENTS.MD", "GEMINI.MD"} or parent_name == "rules"


def _is_plugin_root_rule(path_obj: Path) -> bool:
    """Plugin-bundled rules/AGENTS.md (or GEMINI.md) beside plugin.json is valid without frontmatter."""
    if path_obj.name.upper() not in {"AGENTS.MD", "GEMINI.MD"}:
        return False
    if path_obj.parent.name.lower() != "rules":
        return False
    grandparent = path_obj.parent.parent
    if grandparent.name.lower() in {".agents", "config"}:
        return False
    return (grandparent / "plugin.json").is_file()


def _extract_rule_trigger(frontmatter: str):
    match = re.search(r"^\s*trigger\s*:\s*['\"]?([a-zA-Z0-9_-]+)['\"]?\s*$", frontmatter, re.MULTILINE)
    return match.group(1).lower() if match else None


def check_antigravity_rule_and_plugin(path_obj: Path, full_text: str, lines):
    """Enforce Antigravity-specific rules frontmatter, 24KB limit, and plugin.json constraints."""
    violations = []

    if _is_antigravity_rule_file(path_obj):
        byte_len = len(full_text.encode("utf-8"))
        if byte_len > ANTIGRAVITY_RULE_MAX_BYTES:
            violations.append({
                "file": str(path_obj),
                "line": 1,
                "rule": "RULE_EXCEEDS_24KB",
                "matched": f"{byte_len} bytes",
                "line_text": lines[0].strip()[:120] if lines else "",
                "message": f"Antigravity rule file is {byte_len:,} bytes, exceeding the {ANTIGRAVITY_RULE_MAX_BYTES:,}-byte truncation limit.",
                "severity": "ERROR",
                "fix": "Split large rules into trigger-scoped modular files or concise imperatives below 24,000 bytes.",
            })

        frontmatter = _parse_yaml_frontmatter(full_text)
        is_modular_rules_dir = path_obj.parent.name.lower() == "rules"
        if is_modular_rules_dir and not _is_plugin_root_rule(path_obj):
            if frontmatter is None:
                violations.append({
                    "file": str(path_obj),
                    "line": 1,
                    "rule": "RULE_MISSING_TRIGGER",
                    "matched": path_obj.name,
                    "line_text": lines[0].strip()[:120] if lines else "",
                    "message": "Files inside rules/ (outside a plugin root AGENTS.md) require YAML frontmatter with 'trigger:'. Antigravity silently discards frontmatter-free files in rules/.",
                    "severity": "ERROR",
                    "fix": "Add YAML frontmatter with trigger (always_on, model_decision, glob, or manual), or move frontmatter-free AGENTS.md to ~/.gemini/config/AGENTS.md.",
                })
            else:
                trigger = _extract_rule_trigger(frontmatter)
                if trigger not in VALID_RULE_TRIGGERS:
                    violations.append({
                        "file": str(path_obj),
                        "line": 1,
                        "rule": "RULE_MISSING_TRIGGER",
                        "matched": f"trigger={trigger}",
                        "line_text": lines[0].strip()[:120] if lines else "",
                        "message": f"Invalid or missing Antigravity rule trigger '{trigger}'. Expected one of {sorted(VALID_RULE_TRIGGERS)}.",
                        "severity": "ERROR",
                        "fix": "Set 'trigger: always_on' (or model_decision, glob, manual) in YAML frontmatter.",
                    })

        if frontmatter and re.search(r"^\s*globs\s*:\s*\r?\n\s*-\s+", frontmatter, re.MULTILINE):
            line_no = _find_line_for_token(lines, "globs:")
            violations.append({
                "file": str(path_obj),
                "line": line_no,
                "rule": "RULE_GLOBS_YAML_LIST",
                "matched": "globs: [...]",
                "line_text": lines[line_no - 1].strip()[:120] if line_no <= len(lines) else "",
                "message": "Antigravity requires 'globs:' in rule frontmatter to be a comma-separated string, not a YAML list.",
                "severity": "ERROR",
                "fix": 'Replace YAML array with a comma-separated string, e.g. globs: "*.py, *.ts".',
            })

    if path_obj.name == "plugin.json":
        try:
            pdata = json.loads(full_text)
        except Exception:
            pdata = None
        if isinstance(pdata, dict):
            display_name = pdata.get("displayName")
            if isinstance(display_name, str) and display_name.strip().lower().startswith(FORBIDDEN_PLUGIN_DISPLAY_PREFIXES):
                line_no = _find_line_for_token(lines, "displayName")
                violations.append({
                    "file": str(path_obj),
                    "line": line_no,
                    "rule": "PLUGIN_INVALID_DISPLAY_NAME",
                    "matched": display_name,
                    "line_text": lines[line_no - 1].strip()[:120] if line_no <= len(lines) else "",
                    "message": f"Antigravity plugin displayName '{display_name}' must not start with Antigravity, Gemini, Claude, or Cursor.",
                    "severity": "ERROR",
                    "fix": "Choose a neutral displayName such as 'Token Optimizer'.",
                })
            prompts = pdata.get("suggestedPrompts")
            if isinstance(prompts, list) and len(prompts) > 3:
                line_no = _find_line_for_token(lines, "suggestedPrompts")
                violations.append({
                    "file": str(path_obj),
                    "line": line_no,
                    "rule": "PLUGIN_TOO_MANY_PROMPTS",
                    "matched": f"{len(prompts)} prompts",
                    "line_text": lines[line_no - 1].strip()[:120] if line_no <= len(lines) else "",
                    "message": f"Antigravity plugin suggestedPrompts allows at most 3 items (found {len(prompts)}).",
                    "severity": "ERROR",
                    "fix": "Trim suggestedPrompts in plugin.json to 3 concise entries.",
                })

    return violations


def check_rules_budget(files, strict=False):
    """Check cumulative token footprint of always-on Antigravity rules against 20,000 tokens."""
    total_tokens = 0
    counted_files = []
    for f in files:
        path_obj = Path(f)
        if not _is_antigravity_rule_file(path_obj):
            continue
        try:
            text = path_obj.read_text(encoding="utf-8")
        except Exception:
            continue
        frontmatter = _parse_yaml_frontmatter(text)
        trigger = _extract_rule_trigger(frontmatter) if frontmatter else None
        is_always_active = (
            path_obj.name.upper() in {"AGENTS.MD", "GEMINI.MD"}
            or trigger == "always_on"
        )
        if is_always_active:
            total_tokens += (len(text.encode("utf-8")) + 3) // 4
            counted_files.append(str(path_obj))

    if total_tokens > ANTIGRAVITY_RULES_TOKEN_BUDGET and counted_files:
        return [{
            "file": counted_files[0],
            "line": 1,
            "rule": "RULES_BUDGET_EXCEEDED",
            "matched": f"{total_tokens} tokens across {len(counted_files)} file(s)",
            "line_text": "",
            "message": f"Always-on Antigravity rules total ~{total_tokens:,} tokens, exceeding the {ANTIGRAVITY_RULES_TOKEN_BUDGET:,}-token global budget before pointer demotion.",
            "severity": "ERROR" if strict else "WARNING",
            "fix": "Move task-specific rules to trigger: model_decision or glob, or prune redundant wording.",
        }]
    return []


def check_file(file_path, strict=False):
    """Scan a single file for prompt cache invalidation patterns."""
    violations = []
    path_obj = Path(file_path)

    if not path_obj.exists():
        return [{"file": str(file_path), "line": 0, "rule": "FILE_NOT_FOUND", "message": "File does not exist", "severity": "ERROR"}]

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as exc:
        return [{"file": str(file_path), "line": 0, "rule": "READ_ERROR", "message": str(exc), "severity": "ERROR"}]

    full_text = "".join(lines)
    is_python_source = path_obj.suffix.lower() == ".py"

    # Determine prefix boundary if an explicit dynamic tail marker is present
    tail_line_idx = None
    for line_idx, line in enumerate(lines, start=1):
        if TAIL_MARKER_PATTERN.search(line):
            tail_line_idx = line_idx
            break

    prefix_lines = lines[: tail_line_idx - 1] if tail_line_idx is not None else lines
    prefix_text = "".join(prefix_lines)

    for line_idx, line in enumerate(prefix_lines, start=1):
        stripped = line.strip()
        if INLINE_IGNORE_PATTERN.search(line):
            continue

        for rule in LINT_RULES:
            match = rule["regex"].search(line)
            if match:
                if is_python_source and ("re.compile" in line or '"regex":' in line):
                    continue
                if is_python_source and rule["id"] == "IN_PLACE_PROMPT_MUTATION" and stripped.startswith(("def ", "async def ")):
                    continue
                severity = "ERROR" if (strict or rule["severity"] == "ERROR") else "WARNING"
                violations.append({
                    "file": str(file_path),
                    "line": line_idx,
                    "rule": rule["id"],
                    "matched": match.group(0),
                    "line_text": stripped[:120],
                    "message": rule["description"],
                    "severity": severity,
                    "fix": rule["fix"],
                })

    # Check Antigravity-specific rules frontmatter, 24KB limit, and plugin.json constraints
    violations.extend(check_antigravity_rule_and_plugin(path_obj, full_text, lines))

    # Check for unsorted tool definitions across JSON, YAML, or code blocks
    tool_violations = check_tool_ordering(file_path, lines, full_text)
    violations.extend(tool_violations)

    # Check for multi-line dynamic interpolation evasion attempts in prefix scope
    multiline_interpolation = re.compile(
        r"{{\s*(?:timestamp|date|time|now|uuid|session_id|request_id|nonce)\s*}}",
        re.IGNORECASE | re.DOTALL,
    )
    for match in multiline_interpolation.finditer(prefix_text):
        matched_str = match.group(0)
        if "\n" in matched_str:
            start_pos = match.start()
            line_idx = prefix_text[:start_pos].count("\n") + 1
            violations.append({
                "file": str(file_path),
                "line": line_idx,
                "rule": "DYNAMIC_INTERPOLATION",
                "matched": matched_str.replace("\n", " ")[:60],
                "line_text": matched_str.replace("\n", " ")[:120],
                "message": "Dynamic template interpolation in prompt prefix",
                "severity": "ERROR",
                "fix": "Move dynamic variables from system prompt prefix to the tail of user turns.",
            })

    return violations


def collect_target_files(targets, include_tests=False):
    """Expand file and directory targets into individual file paths."""
    resolved_files = []
    supported_extensions = {".md", ".txt", ".json", ".py", ".prompt", ".yaml", ".yml"}
    excluded_dirs = {"__pycache__", "scratch", "logs", "node_modules", ".git"}
    if not include_tests:
        excluded_dirs.add("tests")

    for target in targets:
        p = Path(target)
        if p.is_file():
            resolved_files.append(p)
        elif p.is_dir():
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in excluded_dirs]
                for file_name in files:
                    file_path = Path(root) / file_name
                    if file_path.suffix.lower() in supported_extensions:
                        resolved_files.append(file_path)

    return sorted(list(set(resolved_files)))


def main():
    parser = argparse.ArgumentParser(
        description="Google Antigravity Prefix Linter: Guard Gemini KV cache prefix invariance."
    )
    parser.add_argument("targets", nargs="+", help="Files or directories to lint")
    parser.add_argument("--strict", action="store_true", help="Treat all warnings as errors")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    parser.add_argument("--include-tests", action="store_true", help="Include tests/ directories when scanning folders")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose inspection logs")

    args = parser.parse_args()

    files = collect_target_files(args.targets, include_tests=args.include_tests)
    if not files:
        if args.json:
            print(json.dumps({"status": "error", "message": "No matching files found to lint"}))
        else:
            print("No matching files found to lint.")
        sys.exit(1)

    all_violations = []
    for f in files:
        violations = check_file(f, strict=args.strict)
        all_violations.extend(violations)

    all_violations.extend(check_rules_budget(files, strict=args.strict))

    error_count = sum(1 for v in all_violations if v["severity"] == "ERROR")
    warning_count = sum(1 for v in all_violations if v["severity"] == "WARNING")

    if args.json:
        report = {
            "status": "failed" if error_count > 0 else "passed",
            "files_scanned": len(files),
            "error_count": error_count,
            "warning_count": warning_count,
            "violations": all_violations,
        }
        print(json.dumps(report, indent=2))
    else:
        print("Google Antigravity Prefix Linter")
        print(f"Scanned {len(files)} file(s).")
        print("-" * 60)

        if all_violations:
            for v in all_violations:
                tag = f"[{v['severity']}]"
                print(f"{tag} {v['file']}:{v['line']} - {v['rule']}")
                print(f"  Matched: '{v['matched']}'")
                print(f"  Snippet: {v['line_text']}")
                print(f"  Remediation: {v['fix']}")
                print()

        print("-" * 60)
        print(f"Summary: {error_count} error(s), {warning_count} warning(s).")

        if error_count == 0:
            print("PASS: All inspected files preserve Gemini KV prompt cache prefix invariance.")
        else:
            print("FAIL: Dynamic tokens detected in prefix sections. Fix errors to restore prompt caching.")

    sys.exit(1 if error_count > 0 else 0)


if __name__ == "__main__":
    main()
