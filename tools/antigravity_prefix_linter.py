#!/usr/bin/env python3
"""Google Antigravity Prefix Linter.

Audits Antigravity rules files, prompt configurations, and template headers
for dynamic variables (timestamps, UUIDs, nonces, session identifiers) that
invalidate Google Gemini KV cache prefix hashing.
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
]


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

    for line_idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        # Skip comment lines that document rules rather than defining prompt prefixes
        if stripped.startswith("#") and "Google Antigravity" in stripped:
            continue

        for rule in LINT_RULES:
            match = rule["regex"].search(line)
            if match:
                # Discard match if this line is explaining the rule (e.g. docstring or documentation)
                if "regex" in line or "pattern" in line or "rule" in line:
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
