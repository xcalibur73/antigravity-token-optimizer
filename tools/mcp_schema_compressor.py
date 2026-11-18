#!/usr/bin/env python3
"""MCP Schema Compressor for Google Antigravity.

Enforces Invariant 6 (Deterministic Tool Schema Ordering) and compresses
verbose MCP tool definitions before registration at the prompt head.

By default, operates losslessly:
- Deterministically sorts tool declarations, dictionary keys, and required arrays.
- Prunes redundant nulls, `$schema` boilerplate, redundant titles, and empty containers.
- Trims leading/trailing description whitespace without dropping instructions.

With `--condense-descriptions` (`condense=True`), also condenses verbose
markdown docstrings into single-sentence noun phrases while preserving
range, default, and allowed-value constraints.
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

TOOL_ARRAY_KEYS = {"tools", "function_declarations", "functions"}


def condense_description(desc: str) -> str:
    """Condense verbose markdown docstring to a concise single-sentence noun phrase."""
    if not desc or not isinstance(desc, str):
        return ""

    # Replace unicode dashes with standard hyphens
    text = desc.replace("\u2014", "-").replace("\u2013", "-")

    # Remove markdown headings, bold, italic, code ticks
    text = re.sub(r"^#+\s+.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`]", "", text)

    # Remove markdown list prefixes
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)

    # Strip multi-newlines and collapse spaces
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""

    # Preamble removal
    text = re.sub(r"^This is a tool from the [^.]*?\.\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"^This tool (?:is used to|allows you to|can be used to|is designed to|serves to|helps to)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^(?:Use this tool to|Used to|Allows you to)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"^(?:A utility to|A tool to|A helper to|A function to|Function to)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^An? (?:tool|utility|helper|function) (?:that|which)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Capitalize the first letter if lowered
    if text and text[0].islower():
        text = text[0].upper() + text[1:]

    # Split into sentences
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        return ""

    primary = sentences[0]
    if primary.endswith((".", "!", "?")):
        clean_primary = primary[:-1].strip()
    else:
        clean_primary = primary

    # Search subsequent sentences for constraints (ranges, defaults, allowed values)
    constraints = []
    rest_text = " ".join(sentences[1:])

    # Range: e.g. "500 to 10000" or "(500 to 10000)"
    range_match = re.search(r"\b(\d+\s*to\s*\d+)\b", rest_text, re.IGNORECASE)
    if range_match and range_match.group(1) not in clean_primary:
        constraints.append(f"Range: {range_match.group(1)}")

    # Default: e.g. "Default is 10" or "Default: 10"
    default_match = re.search(r"\bDefault\s*(?:is|:)\s*([^\s.,;)]+)", rest_text, re.IGNORECASE)
    if default_match and "default" not in clean_primary.lower():
        constraints.append(f"Default: {default_match.group(1)}")

    # Allowed/enum: e.g. "Allowed: read, write, admin." or "Allowed values are a, b, c."
    allowed_match = re.search(
        r"\bAllowed(?:\s*values)?\s*(?:are|:)\s*([^.;\n)]+)",
        rest_text,
        re.IGNORECASE,
    )
    if allowed_match and "allowed" not in clean_primary.lower():
        allowed_vals = re.sub(r"\s+", " ", allowed_match.group(1)).strip().rstrip(",")
        if allowed_vals:
            constraints.append(f"Allowed: {allowed_vals}")

    if constraints:
        constraint_str = ", ".join(constraints)
        if clean_primary.endswith(")"):
            clean_primary = f"{clean_primary[:-1]}, {constraint_str})"
        else:
            clean_primary = f"{clean_primary} ({constraint_str})"

    return clean_primary + "."


def get_tool_name(item):
    """Extract tool identifier name from dictionary representation."""
    if isinstance(item, dict):
        return (
            item.get("name")
            or (item.get("function", {}).get("name") if isinstance(item.get("function"), dict) else None)
            or (item.get("tool", {}).get("name") if isinstance(item.get("tool"), dict) else None)
            or ""
        )
    return str(item)


def _is_tool_object_list(node, parent_key):
    """Identify lists of tool definitions rather than arbitrary ordered lists."""
    if not node or not all(isinstance(item, dict) for item in node):
        return False
    if parent_key is not None and parent_key not in TOOL_ARRAY_KEYS:
        return False
    return all(bool(get_tool_name(item)) for item in node)


def compress_schema_node(node, parent_key=None, condense=False):
    """Recursively prune, sort, and optionally condense schema nodes."""
    if isinstance(node, dict):
        cleaned = {}
        for k, v in node.items():
            # Prune null values
            if v is None:
                continue

            # Prune schema boilerplate keys
            if k in {"$schema"}:
                continue

            # Prune redundant title if identical to parent property or node name
            if k == "title" and isinstance(v, str):
                if parent_key and v.lower() == parent_key.lower():
                    continue
                if "name" in node and v.lower() == str(node["name"]).lower():
                    continue

            # Handle description (lossless trim by default; aggressive condense if requested)
            if k == "description" and isinstance(v, str):
                if condense:
                    v_processed = condense_description(v)
                else:
                    v_processed = re.sub(r"\s+", " ", v).strip()
                if not v_processed:
                    continue
                v = v_processed

            # Prune empty container boilerplate
            if isinstance(v, (list, dict)) and len(v) == 0 and k in {"examples", "definitions", "$defs", "enum"}:
                continue

            # Recursively compress child node
            processed_val = compress_schema_node(v, parent_key=k, condense=condense)

            # Skip if value became empty container for boilerplate keys
            if k in {"examples", "definitions", "$defs"} and isinstance(processed_val, (list, dict)) and len(processed_val) == 0:
                continue

            cleaned[k] = processed_val

        # Sort dict keys alphabetically
        return dict(sorted(cleaned.items(), key=lambda pair: pair[0]))

    elif isinstance(node, list):
        # Only sort tool declaration arrays alphabetically by tool name
        if _is_tool_object_list(node, parent_key):
            node = sorted(node, key=lambda item: (get_tool_name(item).lower(), get_tool_name(item)))
        elif parent_key in {"required", "tags", "keywords"} and all(isinstance(item, str) for item in node):
            node = sorted(node)

        return [compress_schema_node(item, parent_key=parent_key, condense=condense) for item in node]

    elif isinstance(node, str) and parent_key == "description":
        return condense_description(node) if condense else re.sub(r"\s+", " ", node).strip()

    return node


def compress_schema(data, condense=False):
    """Compress and deterministically order a parsed schema data structure."""
    return compress_schema_node(data, condense=condense)


def compress_instructions_markdown(text: str) -> str:
    """Losslessly normalize MCP instructions.md files (CRLF->LF, strip trailing whitespace, collapse 3+ blank lines)."""
    if not text:
        return ""
    normalized_lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    joined = "\n".join(normalized_lines)
    collapsed = re.sub(r"\n{3,}", "\n\n", joined).strip()
    return (collapsed + "\n") if collapsed else ""


def serialize_schema(data, minify=False):
    """Serialize schema data to JSON string."""
    if minify:
        return json.dumps(data, separators=(",", ":"), sort_keys=True)
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def calculate_metrics(raw_text, compressed_text):
    """Calculate token economy metrics (using ~4 chars/token heuristic)."""
    chars_before = len(raw_text)
    chars_after = len(compressed_text)
    tokens_before = int(math.ceil(chars_before / 4.0)) if chars_before > 0 else 0
    tokens_after = int(math.ceil(chars_after / 4.0)) if chars_after > 0 else 0
    pct_reduction = ((chars_before - chars_after) / chars_before * 100.0) if chars_before > 0 else 0.0
    return {
        "chars_before": chars_before,
        "chars_after": chars_after,
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "chars_saved": chars_before - chars_after,
        "pct_reduction": pct_reduction,
    }


def print_metrics(metrics, stream=sys.stderr):
    """Print human-readable token economy metrics table."""
    stream.write("==================================================\n")
    stream.write("MCP Schema Token Economy Summary\n")
    stream.write("==================================================\n")
    stream.write(f"Original size:     {metrics['chars_before']:,} chars (~{metrics['tokens_before']:,} tokens)\n")
    stream.write(f"Compressed size:   {metrics['chars_after']:,} chars (~{metrics['tokens_after']:,} tokens)\n")
    stream.write(f"Saved:             {metrics['chars_saved']:,} chars (~{metrics['tokens_before'] - metrics['tokens_after']:,} tokens)\n")
    stream.write(f"Reduction:         {metrics['pct_reduction']:.1f}%\n")
    stream.write("==================================================\n")


def main():
    parser = argparse.ArgumentParser(
        description="Google Antigravity MCP Schema Compressor: Enforce deterministic tool ordering and compress schemas."
    )
    parser.add_argument("-i", "--input", help="Input JSON or instructions.md file path (defaults to stdin if omitted)")
    parser.add_argument("-o", "--output", help="Output file path (defaults to stdout)")
    parser.add_argument("--in-place", action="store_true", help="Modify the input file in place")
    parser.add_argument("--minify", action="store_true", help="Output compact JSON without indentation")
    parser.add_argument(
        "--condense-descriptions",
        action="store_true",
        help="Aggressively condense multi-sentence docstrings into single-sentence noun phrases (opt-in)",
    )
    parser.add_argument(
        "--instructions-md",
        action="store_true",
        help="Treat input as an MCP instructions.md markdown file (auto-detected for .md inputs)",
    )
    parser.add_argument("--check", action="store_true", help="Check if schema is already compressed and sorted; exit code 1 if not")
    parser.add_argument("--info", action="store_true", help="Print token economy metrics")

    args = parser.parse_args()

    # Read input
    is_markdown = bool(args.instructions_md)
    if args.input and args.input != "-":
        input_path = Path(args.input)
        if not input_path.is_file():
            sys.stderr.write(f"Error: Input file '{args.input}' not found.\n")
            sys.exit(1)
        if input_path.suffix.lower() in {".md", ".markdown"}:
            is_markdown = True
        with open(input_path, "r", encoding="utf-8") as f:
            raw_text = f.read()
    else:
        if args.in_place:
            sys.stderr.write("Error: --in-place requires a file path via --input.\n")
            sys.exit(1)
        if hasattr(sys.stdin, "buffer"):
            raw_text = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
        else:
            raw_text = sys.stdin.read()

    if not raw_text.strip():
        sys.stderr.write("Error: Empty input provided.\n")
        sys.exit(1)

    if is_markdown:
        output_text = compress_instructions_markdown(raw_text)
    else:
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            sys.stderr.write(f"Error: Invalid JSON input: {exc}\n")
            sys.exit(1)

        compressed_data = compress_schema(data, condense=args.condense_descriptions)
        output_text = serialize_schema(compressed_data, minify=args.minify)

    metrics = calculate_metrics(raw_text, output_text)

    if args.check:
        is_identical = raw_text.strip() == output_text.strip() if not is_markdown else raw_text == output_text
        if args.info:
            print_metrics(metrics, stream=sys.stderr)
        if is_identical:
            sys.stderr.write("PASS: Schema is deterministically sorted and compressed.\n")
            sys.exit(0)
        else:
            sys.stderr.write("FAIL: Schema requires compression or deterministic sorting.\n")
            sys.exit(1)

    if args.info:
        print_metrics(metrics, stream=sys.stderr)

    if args.in_place:
        with open(args.input, "w", encoding="utf-8") as f:
            f.write(output_text)
    elif args.output and args.output != "-":
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(output_text)
    else:
        sys.stdout.write(output_text)


if __name__ == "__main__":
    main()
