#!/usr/bin/env python3
"""Google Antigravity Transcript Analyzer.

Audits real Antigravity `transcript.jsonl` logs across Desktop (`~/.gemini/antigravity/brain`),
IDE (`~/.gemini/antigravity-ide/brain`), and CLI (`~/.gemini/jetski/brain`) to measure:
- Actual KV prompt cache hit rates (`usageMetadata` / char-based estimation fallback)
- `O(1)` reverse byte-seek context window health (`--tail`)
- Top 5 token consumers & redundant/failing tool loops
- Oversized unredacted tool/terminal outputs (> 30 lines)
- Consecutive busy-wait polling calls (`manage_task`/`manage_subagents`)
- Unbounded full-file inspections (`view_file` missing StartLine/EndLine)
- Zero-loss `<CONTEXT_SUMMARY>` handoff prompts (`--handoff`)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ANTIGRAVITY_RUNTIME_ROOTS = (
    ("cli", ".gemini/jetski/brain"),
    ("desktop", ".gemini/antigravity/brain"),
    ("ide", ".gemini/antigravity-ide/brain"),
)

DEFAULT_CONTEXT_LIMIT = 200_000


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


def _extract_title_from_log(log_path: Path) -> str:
    """Read only the leading lines of transcript.jsonl to extract a human-readable session title."""
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for _ in range(25):
                line = f.readline()
                if not line:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    entry = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") == "USER_INPUT" or entry.get("role") == "user":
                    text = entry.get("content") or ""
                    if not isinstance(text, str):
                        text = json.dumps(text)
                    if "<USER_REQUEST>" in text and "</USER_REQUEST>" in text:
                        text = text.split("<USER_REQUEST>", 1)[1].split("</USER_REQUEST>", 1)[0]
                    clean = re.sub(r"<[^>]+>", " ", text)
                    clean = re.sub(r"[#*_`]+", " ", clean)
                    for subline in clean.splitlines():
                        s = " ".join(subline.split())
                        if s:
                            return s[:80]
    except OSError:
        pass
    return log_path.parent.parent.parent.name[:12]


def discover_transcripts(home_dir: Path | None = None, limit: int = 20) -> list[dict]:
    """Discover real Antigravity transcript.jsonl files across CLI, Desktop, and IDE brains."""
    base_home = Path(home_dir) if home_dir is not None else Path.home()
    found = []

    for runtime, rel_root in ANTIGRAVITY_RUNTIME_ROOTS:
        brain_root = base_home / rel_root
        if not brain_root.is_dir():
            continue
        try:
            for log_path in brain_root.rglob("transcript.jsonl"):
                if log_path.parent.name != "logs" or log_path.parent.parent.name != ".system_generated":
                    continue
                if not log_path.is_file():
                    continue
                try:
                    st = log_path.stat()
                    conv_id = log_path.parent.parent.parent.relative_to(brain_root).as_posix()
                except (OSError, ValueError):
                    continue
                found.append({
                    "conversation_id": conv_id,
                    "runtime": runtime,
                    "path": str(log_path),
                    "size_bytes": st.st_size,
                    "mtime": st.st_mtime,
                    "modified_utc": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
                    "title": _extract_title_from_log(log_path),
                })
        except OSError:
            continue

    found.sort(key=lambda item: item["mtime"], reverse=True)
    return found[:limit]


def _classify_health(usage_pct: float) -> str:
    if usage_pct >= 90.0:
        return "Critical"
    if usage_pct >= 75.0:
        return "Warning"
    if usage_pct >= 50.0:
        return "Moderate"
    return "Optimal"


def inspect_tail_health(
    jsonl_path: Path,
    context_limit: int = DEFAULT_CONTEXT_LIMIT,
    chunk_bytes: int = 65536,
) -> dict:
    """O(1) reverse byte-seek scan of the tail chunk to read latest context usage without loading full logs."""
    file_size = jsonl_path.stat().st_size
    read_size = min(file_size, max(4096, chunk_bytes))
    offset = max(0, file_size - read_size)

    with open(jsonl_path, "rb") as f:
        f.seek(offset, os.SEEK_SET)
        raw_tail = f.read(read_size).decode("utf-8", errors="replace")

    lines = raw_tail.splitlines()
    if offset > 0 and lines:
        # First line may be partial if seek landed mid-line
        lines = lines[1:]

    latest_usage = None
    latest_step_index = None
    parsed_tail_steps = 0
    tail_est_tokens = 0

    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rec = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        parsed_tail_steps += 1
        content = rec.get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content)
        tail_est_tokens += _estimate_tokens(content)

        if latest_usage is None:
            usage = _extract_usage(rec)
            if usage is not None:
                latest_usage = usage
                latest_step_index = rec.get("step_index")

    effective_tokens = latest_usage["prompt_tokens"] if latest_usage else tail_est_tokens
    usage_pct = round((effective_tokens / context_limit) * 100.0, 2) if context_limit > 0 else 0.0
    health = _classify_health(usage_pct)

    return {
        "file": str(jsonl_path),
        "file_size_bytes": file_size,
        "tail_bytes_scanned": read_size,
        "tail_steps_parsed": parsed_tail_steps,
        "context_limit": context_limit,
        "latest_step_index": latest_step_index,
        "latest_usage": latest_usage,
        "estimated_tail_tokens": tail_est_tokens,
        "context_utilization_pct": usage_pct,
        "health": health,
    }


def _describe_step_consumer(step: dict, step_id, content: str, tool_calls: list) -> tuple[str, int]:
    """Compute a human-readable consumer label and token footprint for a transcript step."""
    usage = _extract_usage(step)
    est = _estimate_tokens(content)
    for call in tool_calls:
        if isinstance(call, dict):
            est += _estimate_tokens(json.dumps(call))

    step_type = str(step.get("type", "STEP"))
    if tool_calls:
        names = [str(c.get("name") or c.get("tool") or "tool") for c in tool_calls if isinstance(c, dict)]
        label = f"Step #{step_id} ({step_type}: {', '.join(names[:3])})"
    else:
        label = f"Step #{step_id} ({step_type})"

    # Use output/content tokens rather than cumulative prompt_tokens so ranking identifies incremental bloat
    score_tokens = est if est > 0 else (usage["output_tokens"] if usage else 0)
    return label, score_tokens


def analyze_transcript(jsonl_path: Path, context_limit: int = DEFAULT_CONTEXT_LIMIT) -> dict:
    """Parse a JSONL transcript and compute real token, cache, top-consumer, and invariant diagnostics."""
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
    latest_prompt_tokens = 0

    oversized_outputs = []
    unbounded_reads = []
    polling_sequences = []
    redundant_tool_loops = []
    consumers = []

    consecutive_polls = 0
    poll_start_step = None

    last_call_sig = None
    consecutive_same_call = 0
    same_call_start_step = None

    for idx, step in enumerate(steps):
        step_id = step.get("step_index", idx)
        step_type = str(step.get("type", ""))
        content = step.get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content)

        step_content_tokens = _estimate_tokens(content)
        estimated_content_tokens += step_content_tokens

        usage = _extract_usage(step)
        if usage is not None:
            usage_steps += 1
            total_prompt_tokens += usage["prompt_tokens"]
            total_cached_tokens += usage["cached_tokens"]
            total_output_tokens += usage["output_tokens"]
            latest_prompt_tokens = usage["prompt_tokens"]

        # Detect oversized tool/command outputs in content
        line_count = content.count("\n") + (1 if content else 0)
        if step_type in {"TOOL_RESPONSE", "COMMAND_OUTPUT", "OBSERVATION"} or "The command exited with code" in content:
            if line_count > 30:
                oversized_outputs.append({
                    "step_index": step_id,
                    "lines": line_count,
                    "estimated_tokens": step_content_tokens,
                })

        # Inspect tool calls
        tool_calls = step.get("tool_calls") or []
        if not isinstance(tool_calls, list):
            tool_calls = []

        label, consumer_tokens = _describe_step_consumer(step, step_id, content, tool_calls)
        if consumer_tokens > 0:
            consumers.append({
                "step_index": step_id,
                "label": label,
                "estimated_tokens": consumer_tokens,
                "lines": line_count,
            })

        step_had_poll = False
        step_sigs = []
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

            if name in {"view_file", "read_file"} and isinstance(args, dict):
                if args.get("StartLine") is None and args.get("EndLine") is None and args.get("startLine") is None and args.get("endLine") is None:
                    unbounded_reads.append({
                        "step_index": step_id,
                        "path": args.get("AbsolutePath") or args.get("file_path") or args.get("path") or "<unknown>",
                    })

            if name in {"manage_task", "manage_subagents"} and isinstance(args, dict):
                action = str(args.get("Action") or args.get("action") or "").lower()
                if action in {"status", "list"}:
                    step_had_poll = True

            if name:
                sig = f"{name}:{json.dumps(args, sort_keys=True) if isinstance(args, dict) else str(args)}"
                step_sigs.append(sig)

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

        if len(step_sigs) == 1 and not step_had_poll:
            sig = step_sigs[0]
            if sig == last_call_sig:
                consecutive_same_call += 1
            else:
                if consecutive_same_call >= 3 and last_call_sig:
                    redundant_tool_loops.append({
                        "start_step": same_call_start_step,
                        "tool": last_call_sig.split(":", 1)[0],
                        "repeats": consecutive_same_call,
                    })
                last_call_sig = sig
                consecutive_same_call = 1
                same_call_start_step = step_id
        elif step_sigs:
            if consecutive_same_call >= 3 and last_call_sig:
                redundant_tool_loops.append({
                    "start_step": same_call_start_step,
                    "tool": last_call_sig.split(":", 1)[0],
                    "repeats": consecutive_same_call,
                })
            last_call_sig = None
            consecutive_same_call = 0
            same_call_start_step = None

    if consecutive_polls >= 2:
        polling_sequences.append({
            "start_step": poll_start_step,
            "consecutive_polls": consecutive_polls,
        })
    if consecutive_same_call >= 3 and last_call_sig:
        redundant_tool_loops.append({
            "start_step": same_call_start_step,
            "tool": last_call_sig.split(":", 1)[0],
            "repeats": consecutive_same_call,
        })

    cache_hit_rate_pct = (
        round((total_cached_tokens / total_prompt_tokens) * 100.0, 2)
        if total_prompt_tokens > 0
        else None
    )

    consumers.sort(key=lambda c: c["estimated_tokens"], reverse=True)
    top_consumers = consumers[:5]

    active_tokens = latest_prompt_tokens if latest_prompt_tokens > 0 else estimated_content_tokens
    context_util_pct = round((active_tokens / context_limit) * 100.0, 2) if context_limit > 0 else 0.0

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
            "latest_prompt_tokens": latest_prompt_tokens,
        },
        "estimated_content_tokens": estimated_content_tokens,
        "context_health": {
            "context_limit": context_limit,
            "active_tokens": active_tokens,
            "utilization_pct": context_util_pct,
            "status": _classify_health(context_util_pct),
        },
        "findings": {
            "oversized_outputs_over_30_lines": oversized_outputs,
            "unbounded_view_file_calls": unbounded_reads,
            "busy_wait_polling_sequences": polling_sequences,
            "redundant_tool_loops": redundant_tool_loops,
            "top_consumers": top_consumers,
        },
    }


def generate_handoff_summary(jsonl_path: Path, context_limit: int = DEFAULT_CONTEXT_LIMIT) -> str:
    """Generate a compact <CONTEXT_SUMMARY> migration prompt for zero-loss Antigravity session rollover."""
    user_requests = []
    modified_files = []
    inspected_files = []
    seen_modified = set()
    seen_inspected = set()
    latest_prompt_tokens = 0
    total_steps = 0

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                step = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            total_steps += 1
            usage = _extract_usage(step)
            if usage:
                latest_prompt_tokens = usage["prompt_tokens"]

            step_type = str(step.get("type", ""))
            content = step.get("content") or ""
            if (step_type == "USER_INPUT" or step.get("role") == "user") and isinstance(content, str):
                text = content
                if "<USER_REQUEST>" in text and "</USER_REQUEST>" in text:
                    text = text.split("<USER_REQUEST>", 1)[1].split("</USER_REQUEST>", 1)[0]
                cleaned = " ".join(text.strip().split())
                if cleaned and cleaned not in user_requests:
                    user_requests.append(cleaned[:200])

            for call in step.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                name = str(call.get("name") or call.get("tool") or "")
                args = call.get("arguments") or call.get("args") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                if not isinstance(args, dict):
                    continue
                target = args.get("TargetFile") or args.get("AbsolutePath") or args.get("file_path") or args.get("path")
                if not isinstance(target, str) or not target:
                    continue
                if name in {"replace_file_content", "multi_replace_file_content", "write_to_file", "edit_file", "write_file"}:
                    if target not in seen_modified:
                        seen_modified.add(target)
                        modified_files.append(target)
                elif name in {"view_file", "read_file"}:
                    if target not in seen_inspected:
                        seen_inspected.add(target)
                        inspected_files.append(target)

    lines = [
        "<CONTEXT_SUMMARY>",
        f"Source Transcript: {jsonl_path}",
        f"Progress: {total_steps} recorded steps | Latest Context: {latest_prompt_tokens:,} / {context_limit:,} tokens",
        "",
        "## User Requests",
    ]
    if user_requests:
        for idx, req in enumerate(user_requests[-5:], start=1):
            lines.append(f"{idx}. {req}")
    else:
        lines.append("1. Continue the current task in this workspace.")

    lines.append("")
    lines.append("## Modified Files")
    if modified_files:
        for path in modified_files[-15:]:
            lines.append(f"- `{path}`")
    else:
        lines.append("- None recorded in transcript tool calls.")

    lines.append("")
    lines.append("## Recently Inspected Files")
    if inspected_files:
        for path in inspected_files[-10:]:
            lines.append(f"- `{path}`")
    else:
        lines.append("- None recorded.")

    lines.extend([
        "",
        "## Next Action",
        "Resume from the modified files above using line-bounded `view_file` slices (<= 150 lines) and scratch-log redirection for verbose terminal output.",
        "</CONTEXT_SUMMARY>",
    ])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="Analyze real Antigravity JSONL transcripts for KV cache hits, context health, and waste."
    )
    parser.add_argument("transcript", nargs="?", help="Path to transcript.jsonl file (or pass --latest)")
    parser.add_argument("--list", action="store_true", help="List discovered Antigravity transcripts across CLI, Desktop, and IDE")
    parser.add_argument("--latest", action="store_true", help="Automatically select the most recently modified Antigravity transcript")
    parser.add_argument("--tail", action="store_true", help="Run O(1) reverse byte-seek context health check on transcript tail")
    parser.add_argument("--handoff", action="store_true", help="Generate a compact <CONTEXT_SUMMARY> migration prompt")
    parser.add_argument("--context-limit", type=int, default=DEFAULT_CONTEXT_LIMIT, help="Context window size for health percentage (default: 200000)")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args()

    if args.list:
        sessions = discover_transcripts()
        if args.json:
            print(json.dumps({"sessions": sessions}, indent=2))
            return
        if not sessions:
            print("No Antigravity transcripts found under ~/.gemini/{jetski,antigravity,antigravity-ide}/brain.")
            return
        print(f"Discovered {len(sessions)} Antigravity transcript(s):")
        for s in sessions:
            print(f"- [{s['runtime']}] {s['modified_utc']} | {s['size_bytes']:,} B | {s['title']} -> {s['path']}")
        return

    if args.latest:
        sessions = discover_transcripts(limit=1)
        if not sessions:
            sys.stderr.write("Error: No Antigravity transcripts found under ~/.gemini/{jetski,antigravity,antigravity-ide}/brain.\n")
            sys.exit(1)
        path = Path(sessions[0]["path"])
    elif args.transcript:
        path = Path(args.transcript)
    else:
        parser.error("Provide a transcript.jsonl path, --latest, or --list.")
        return

    if not path.is_file():
        sys.stderr.write(f"Error: Transcript file '{path}' not found.\n")
        sys.exit(1)

    if args.handoff:
        summary = generate_handoff_summary(path, context_limit=args.context_limit)
        if args.json:
            print(json.dumps({"file": str(path), "handoff_markdown": summary}, indent=2))
        else:
            sys.stdout.write(summary)
        return

    if args.tail:
        tail_report = inspect_tail_health(path, context_limit=args.context_limit)
        if args.json:
            print(json.dumps(tail_report, indent=2))
            return
        print("=" * 68)
        print("Google Antigravity Tail Health Check (O(1) Reverse Seek)")
        print("=" * 68)
        print(f"Transcript File          : {tail_report['file']}")
        print(f"File Size                : {tail_report['file_size_bytes']:,} bytes (scanned last {tail_report['tail_bytes_scanned']:,} bytes)")
        print(f"Health Status            : {tail_report['health']} ({tail_report['context_utilization_pct']:.2f}% of {tail_report['context_limit']:,})")
        if tail_report["latest_usage"]:
            u = tail_report["latest_usage"]
            print(f"Latest Prompt Tokens     : {u['prompt_tokens']:,} (cached: {u['cached_tokens']:,})")
        else:
            print(f"Estimated Tail Tokens    : ~{tail_report['estimated_tail_tokens']:,}")
        print("=" * 68)
        return

    try:
        report = analyze_transcript(path, context_limit=args.context_limit)
    except ValueError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        sys.exit(1)

    if args.json:
        print(json.dumps(report, indent=2))
        return

    measured = report["measured_tokens"]
    findings = report["findings"]
    health = report["context_health"]
    print("=" * 68)
    print("Google Antigravity Transcript Audit")
    print("=" * 68)
    print(f"Transcript File          : {report['file']}")
    print(f"Total Steps              : {report['total_steps']}")
    print(f"Steps w/ Usage Metadata  : {report['steps_with_usage_metadata']}")
    print(f"Context Health           : {health['status']} ({health['utilization_pct']:.2f}% of {health['context_limit']:,})")
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
    print(f"Redundant Tool Loops     : {len(findings['redundant_tool_loops'])}")
    if findings["top_consumers"]:
        print("-" * 68)
        print("Top Token Consumers:")
        for item in findings["top_consumers"]:
            print(f"  - {item['label']}: ~{item['estimated_tokens']:,} tokens ({item['lines']} lines)")
    print("=" * 68)


if __name__ == "__main__":
    main()
