---
name: token-optimizer
description: Enforce Gemini KV prompt caching invariants, run prefix linter audits, analyze transcript traces, and compress MCP tool schemas for Google Antigravity.
---

# Token Optimizer Skill

This skill enforces strict prompt caching and token optimization invariants across Google Antigravity agent sessions. Follow these procedures to maintain byte-for-byte prefix hash stability and protect context windows.

## Core Invariants

1. Prefix invariance: Keep system prompts, rules, and tool declarations leading and static. Relocate dynamic timestamps, UUIDs, and session identifiers to the tail of user turns.
2. Context shielding: Offload multi-file edits, extensive exploration, and heavy test trial loops to background subagents.
3. Stream distillation: Redirect verbose terminal output exceeding 30 lines to scratch logs and inspect using head-and-tail pointers.
4. Line-bounded inspection: Pass `StartLine` and `EndLine` to restrict file reads to at most 150 lines per tool call.
5. Reactive scheduling: Yield coordinator turns with zero tool calls after task dispatch and use native reactive wakeups or `schedule` watchdogs instead of polling.
6. Deterministic schema ordering: Alphabetically sort tool definitions and parameter schemas before prompt registration.
7. Append-only updates: Append environment deltas and working directory changes to conversation tails rather than mutating history in place.

## Tool Verification Commands

Run the prefix linter from the `antigravity-token-optimizer` repository (or pass the installed script path):

```bash
python tools/antigravity_prefix_linter.py rules/AGENTS.md --strict
python tools/antigravity_prefix_linter.py path/to/prompts/ --strict
```

Sort and compress MCP schemas deterministically (lossless by default; add `--condense-descriptions` to opt into single-sentence docstring condensation, or pass `instructions.md` directly):

```bash
python tools/mcp_schema_compressor.py --input schema.json --output sorted.json --info
python tools/mcp_schema_compressor.py --input schema.json --in-place
python tools/mcp_schema_compressor.py --input schema.json --in-place --condense-descriptions
python tools/mcp_schema_compressor.py --input instructions.md --in-place
python tools/mcp_schema_compressor.py --input schema.json --check
```

Audit real Antigravity JSONL transcripts across CLI (`antigravity-cli` / `jetski`), Desktop, and IDE brains:

```bash
python tools/transcript_analyzer.py --list
python tools/transcript_analyzer.py --latest
python tools/transcript_analyzer.py --latest --tail
python tools/transcript_analyzer.py --latest --handoff
python tools/transcript_analyzer.py /path/to/transcript.jsonl --json
```

Run test suite verification:

```bash
python -m unittest discover -s tests -v
```
