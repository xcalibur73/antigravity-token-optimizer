#!/usr/bin/env python3
"""Google Antigravity Transcript Analyzer.

Audits real Antigravity `transcript.jsonl` logs (or Gemini API JSONL traces) to
measure actual token footprints, KV cache hit rates (when usage metadata is
present), and context-waste anti-patterns:
- Oversized unredacted tool/terminal outputs (> 30 lines)
- Consecutive busy-wait polling calls (`manage_task`/`manage_subagents` status loops)
- Unbounded full-file inspections (`view_file` calls missing StartLine/EndLine)
"""

import argparse
import json
import math
import sys
from pathlib import Path


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return int(math.ceil(len(text) / 4.0))


def _extract_usage(record: dict):
    """Extract prompt, cached, and output token counts from Gemini/Antigravity metadata if present."""
    usage = (
        record.get("usageMetadata")
        or record.get("usage_metadata")
        or record.get("usage")
        or {}
    )
    if not isinstance(usage, dict):
        return None

    prompt_tokens = usage.get("promptTokenCount")
    if prompt_tokens is None:
        prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")

    cached_tokens = usage.get("cachedContentTokenCount")
    if cached_tokens is None:
        cached_tokens = usage.get("cached_tokens") or 0

    output_tokens = usage.get("candidatesTokenCount")
    if output_tokens is None:
        output_tokens = usage.get("completion_tokens") or usage.get("output_tokens") or 0

    if prompt_tokens is None:
        return None

    return {
        "prompt_tokens": int(prompt_tokens),
        "cached_tokens": int(cached_tokens or 0),
        "output_tokens": int(output_tokens or 0),
    }


def analyze_transcript(jsonl_path: Path) -> dict:
    """Parse a JSONL transcript and compute real token & invariant diagnostics."""
    steps = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                steps.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_no}: {exc}") from exc

    total_prompt_tokens = 0
    total_cached_tokens = 0
    total_output_tokens = 0
    usage_steps = 0
    estimated_content_tokens = 0

    oversized_outputs = []
    unbounded_reads = []
    polling_sequences = []
    consecutive_polls = 0
    poll_start_step = None

    for idx, step in enumerate(steps):
        step_id = step.get("step_index", idx)
        step_type = str(step.get("type", ""))
        content = step.get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content)

        estimated_content_tokens += _estimate_tokens(content)

        usage = _extract_usage(step)
        if usage is not None:
            usage_steps += 1
            total_prompt_tokens += usage["prompt_tokens"]
            total_cached_tokens += usage["cached_tokens"]
            total_output_tokens += usage["output_tokens"]

        # Detect oversized tool/command outputs in content
        line_count = content.count("\n") + (1 if content else 0)
        if step_type in {"TOOL_RESPONSE", "COMMAND_OUTPUT", "OBSERVATION"} or "The command exited with code" in content:
            if line_count > 30:
                oversized_outputs.append({
                    "step_index": step_id,
                    "lines": line_count,
                    "estimated_tokens": _estimate_tokens(content),
                })

        # Inspect tool calls
        tool_calls = step.get("tool_calls") or []
        if not isinstance(tool_calls, list):
            tool_calls = []

        step_had_poll = False
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            name = str(call.get("name") or call.get("tool") or "")
            args = call.get("arguments") or call.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}

            if name == "view_file" and isinstance(args, dict):
                if args.get("StartLine") is None and args.get("EndLine") is None:
                    unbounded_reads.append({
                        "step_index": step_id,
                        "path": args.get("AbsolutePath", "<unknown>"),
                    })

            if name in {"manage_task", "manage_subagents"} and isinstance(args, dict):
                action = str(args.get("Action") or args.get("action") or "").lower()
                if action in {"status", "list"}:
                    step_had_poll = True

        if step_had_poll:
            if consecutive_polls == 0:
                poll_start_step = step_id
            consecutive_polls += 1
        else:
            if consecutive_polls >= 2:
                polling_sequences.append({
                    "start_step": poll_start_step,
                    "consecutive_polls": consecutive_polls,
                })
            consecutive_polls = 0
            poll_start_step = None

    if consecutive_polls >= 2:
        polling_sequences.append({
            "start_step": poll_start_step,
            "consecutive_polls": consecutive_polls,
        })

    cache_hit_rate_pct = (
        round((total_cached_tokens / total_prompt_tokens) * 100.0, 2)
        if total_prompt_tokens > 0
        else None
    )

    return {
        "file": str(jsonl_path),
        "total_steps": len(steps),
        "steps_with_usage_metadata": usage_steps,
        "measured_tokens": {
            "prompt_tokens": total_prompt_tokens,
            "cached_tokens": total_cached_tokens,
            "uncached_tokens": max(0, total_prompt_tokens - total_cached_tokens),
            "output_tokens": total_output_tokens,
            "cache_hit_rate_pct": cache_hit_rate_pct,
        },
        "estimated_content_tokens": estimated_content_tokens,
        "findings": {
            "oversized_outputs_over_30_lines": oversized_outputs,
            "unbounded_view_file_calls": unbounded_reads,
            "busy_wait_polling_sequences": polling_sequences,
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Analyze real Antigravity JSONL transcripts for KV cache hits and context waste."
    )
    parser.add_argument("transcript", help="Path to transcript.jsonl file")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args()

    path = Path(args.transcript)
    if not path.is_file():
        sys.stderr.write(f"Error: Transcript file '{args.transcript}' not found.\n")
        sys.exit(1)

    try:
        report = analyze_transcript(path)
    except ValueError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        sys.exit(1)

    if args.json:
        print(json.dumps(report, indent=2))
        return

    measured = report["measured_tokens"]
    findings = report["findings"]
    print("=" * 68)
    print("Google Antigravity Transcript Audit")
    print("=" * 68)
    print(f"Transcript File          : {report['file']}")
    print(f"Total Steps              : {report['total_steps']}")
    print(f"Steps w/ Usage Metadata  : {report['steps_with_usage_metadata']}")
    if measured["prompt_tokens"] > 0:
        print(f"Measured Prompt Tokens   : {measured['prompt_tokens']:,}")
        print(f"Measured Cached Tokens   : {measured['cached_tokens']:,}")
        print(f"Measured Uncached Tokens : {measured['uncached_tokens']:,}")
        print(f"Measured Cache Hit Rate  : {measured['cache_hit_rate_pct']:.2f}%")
    else:
        print(f"Estimated Content Tokens : ~{report['estimated_content_tokens']:,} (no usageMetadata in trace)")
    print("-" * 68)
    print(f"Oversized Outputs (>30L) : {len(findings['oversized_outputs_over_30_lines'])}")
    print(f"Unbounded Reads          : {len(findings['unbounded_view_file_calls'])}")
    print(f"Busy-Wait Poll Loops     : {len(findings['busy_wait_polling_sequences'])}")
    print("=" * 68)


if __name__ == "__main__":
    main()
