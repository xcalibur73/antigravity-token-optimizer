#!/usr/bin/env python3
"""Google Antigravity Prefix Linter.

Audits Antigravity rules files, prompt configurations, and template headers
for dynamic variables (timestamps, UUIDs, nonces, session identifiers),
unsorted tool schemas, and in-place prompt mutation patterns that invalidate
Google Gemini KV cache prefix hashing.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path


LINT_RULES = [
    {
        "id": "DYNAMIC_INTERPOLATION",
        "description": "Dynamic template interpolation in prompt prefix",
        "regex": re.compile(r"{{\s*(?:timestamp|date|time|now|uuid|session_id|request_id|nonce)\s*}}", re.IGNORECASE),
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
        "regex": re.compile(r"\b202[0-9]-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9](?:\.\d+)?(?:Z|[+-][0-2][0-9]:?[0-5][0-9])?\b"),
        "severity": "ERROR",
        "fix": "Remove dynamic timestamps from static prefixes. Relocate to user turn footer.",
    },
    {
        "id": "LITERAL_UUID",
        "description": "Literal UUID found in prefix content",
        "regex": re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
        "severity": "WARNING",
        "fix": "Use static identifiers in prompt templates. Place ephemeral UUIDs at user message tail.",
    },
    {
        "id": "DYNAMIC_SESSION_ASSIGNMENT",
        "description": "Dynamic session or request parameter in prefix",
        "regex": re.compile(r"(?:session_id|request_id|turn_nonce|client_nonce)\s*=\s*['\"][^'\"]+['\"]", re.IGNORECASE),
        "severity": "ERROR",
        "fix": "Prefix headers must remain identical across sessions for KV cache reuse.",
    },
    {
        "id": "IN_PLACE_PROMPT_MUTATION",
        "description": "In-place system prompt or conversation history mutation pattern detected",
        "regex": re.compile(
            r"(?:set_system_prompt|update_system_prompt|replace_system_prompt|modify_system_prompt|mutate_system_prompt|reset_system_prompt|replace_system_message)\s*\("
            r"|(?:\.system_prompt|\.system_instruction)\s*=(?!=)"
            r"|(?:messages|history|conversation)\[0\](?:\s*\[['\"][^'\"]+['\"]\])?\s*=(?!=)"
            r"|(?:system_prompt|system_instruction)\.(?:replace|format|update)\s*\(",
            re.IGNORECASE,
        ),
        "severity": "ERROR",
        "fix": "Never mutate system prompts or prior turns in place. Append runtime state updates to conversation tail.",
    },
]


def check_tool_ordering(file_path, lines, text):
    """Scan file content for unsorted tool declarations or tool schemas."""
    violations = []
    path_obj = Path(file_path)

    # 1. Direct JSON check for tool arrays
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
                        name = item.get("name") or item.get("function", {}).get("name") or item.get("tool", {}).get("name")
                        if name:
                            names.append(str(name))
                    elif isinstance(item, str):
                        names.append(item)

                if len(names) >= 2:
                    for i in range(len(names) - 1):
                        if names[i].lower() > names[i + 1].lower():
                            offending_line = 1
                            for idx, line in enumerate(lines, start=1):
                                if names[i + 1] in line:
                                    offending_line = idx
                                    break
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
        except Exception:
            pass

    # 2. Pattern check for code blocks, YAML, Python, Markdown: tools = [ ... ], function_declarations = [ ... ]
    tool_block_pattern = re.compile(
        r"(?:tools|function_declarations|functions)\s*(?:=|:)\s*\[([^\]]+)\]",
        re.IGNORECASE | re.DOTALL,
    )
    for match in tool_block_pattern.finditer(text):
        match_str = match.group(0)
        if path_obj.suffix.lower() == ".py" and ("re.compile" in match_str or "pattern" in match_str or "tool_block_pattern" in match_str):
            continue

        block_content = match.group(1)
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
                names = [m for m in ident_matches if m not in {"tools", "function_declarations", "functions", "None", "True", "False"}]

        if len(names) >= 2:
            for i in range(len(names) - 1):
                if names[i].lower() > names[i + 1].lower():
                    start_char = match.start()
                    line_no = text[:start_char].count("\n") + 1
                    for idx, line in enumerate(lines[line_no - 1:], start=line_no):
                        if names[i + 1] in line:
                            line_no = idx
                            break
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

    # 3. YAML list pattern:
    yaml_tool_pattern = re.compile(
        r"^(?:tools|function_declarations|functions)\s*:\s*\n((?:\s*-\s+.*?\n)+)",
        re.IGNORECASE | re.MULTILINE,
    )
    for match in yaml_tool_pattern.finditer(text):
        yaml_block = match.group(1)
        names = re.findall(r"-\s+(?:name:\s*)?['\"]?([a-zA-Z0-9_-]+)['\"]?", yaml_block)
        if len(names) >= 2:
            for i in range(len(names) - 1):
                if names[i].lower() > names[i + 1].lower():
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

    for line_idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        # Skip comment lines that document rules rather than defining prompt prefixes
        if stripped.startswith("#") and "Google Antigravity" in stripped:
            continue

        for rule in LINT_RULES:
            match = rule["regex"].search(line)
            if match:
                # Only suppress in python source if the line is defining the lint regex itself
                if is_python_source and ("re.compile" in line or '"regex":' in line):
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

    # Check for unsorted tool definitions across JSON, YAML, or code blocks
    tool_violations = check_tool_ordering(file_path, lines, full_text)
    violations.extend(tool_violations)

    # Check for multi-line dynamic interpolation evasion attempts
    multiline_interpolation = re.compile(
        r"{{\s*(?:timestamp|date|time|now|uuid|session_id|request_id|nonce)\s*}}",
        re.IGNORECASE | re.DOTALL,
    )
    for match in multiline_interpolation.finditer(full_text):
        matched_str = match.group(0)
        if "\n" in matched_str:
            start_pos = match.start()
            line_idx = full_text[:start_pos].count("\n") + 1
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


def collect_target_files(targets):
    """Expand file and directory targets into individual file paths."""
    resolved_files = []
    supported_extensions = {".md", ".txt", ".json", ".py", ".prompt", ".yaml", ".yml"}

    for target in targets:
        p = Path(target)
        if p.is_file():
            resolved_files.append(p)
        elif p.is_dir():
            for root, dirs, files in os.walk(p):
                # Skip hidden directories and scratch caches
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"__pycache__", "scratch", "logs"}]
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
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose inspection logs")

    args = parser.parse_args()

    files = collect_target_files(args.targets)
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
