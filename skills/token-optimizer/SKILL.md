---
name: token-optimizer
description: Enforce Gemini KV prompt caching invariants, run prefix linter audits, and compress MCP tool schemas for Google Antigravity.
---

# Token Optimizer Skill

This skill enforces strict prompt caching and token optimization invariants across Google Antigravity agent sessions. Follow these procedures to maintain byte-for-byte prefix hash stability and protect context windows.

## Core Invariants

1. Prefix invariance: Keep system prompts, rules, and tool declarations leading and static. Relocate dynamic timestamps, UUIDs, and session identifiers to the tail of user turns.
2. Context shielding: Offload multi-file edits, extensive exploration, and heavy test trial loops to background subagents.
3. Stream distillation: Redirect verbose terminal output exceeding 30 lines to scratch logs and inspect using head-and-tail pointers.
4. Line-bounded inspection: Pass StartLine and EndLine to restrict file reads to at most 150 lines per tool call.
5. Reactive scheduling: Yield coordinator turns with zero tool calls after task dispatch and set schedule watchdogs instead of polling.
6. Deterministic schema ordering: Alphabetically sort tool definitions and parameter schemas before prompt registration.
7. Append-only updates: Append environment deltas and working directory changes to conversation tails rather than mutating history in place.

## Tool Verification Commands

Run the prefix linter to verify rules files and prompt templates:

```bash
python tools/antigravity_prefix_linter.py rules/AGENTS.md
python tools/antigravity_prefix_linter.py path/to/prompts/ --strict
```

Compress and sort MCP schemas deterministically:

```bash
python tools/mcp_schema_compressor.py --input schema.json --output compressed.json --info
python tools/mcp_schema_compressor.py --input schema.json --in-place
python tools/mcp_schema_compressor.py --input schema.json --check
```

Run test suite verification:

```bash
python -m unittest discover tests
```
