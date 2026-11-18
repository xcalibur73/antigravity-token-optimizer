# Antigravity Token Optimizer

Google Antigravity Token Optimizer is a context engineering and prompt caching toolkit designed for the Google Antigravity IDE, AGY CLI, and Gemini backbone models. It enforces seven architectural invariants that eliminate prompt cache invalidation, protect coordinator context windows, and prevent terminal stream flooding.

## Executive Summary

Unshielded agent sessions rapidly burn input tokens across multi-turn workflows due to compounding mechanics: dynamic prefix mutation breaking KV prompt caching, non-deterministic tool schema serialization mutating the prompt head, in-place prompt modifications invalidating prior context, unrestricted terminal output dumping thousands of log lines into context, and busy-wait polling loops repeatedly resending conversation histories.

By enforcing the 7 Antigravity Invariants—and verifying them with static prefix linting, deterministic schema compression, and transcript auditing—sessions preserve high KV cache hit rates while keeping coordinator context compact.

## 10-Second Quickstart

Install the Antigravity Token Optimizer invariants non-destructively into your global Antigravity rules configuration (`$HOME/.gemini/config/rules/AGENTS.md` by default):

### Linux / macOS (bash)

```bash
curl -fsSL https://raw.githubusercontent.com/xcalibur73/antigravity-token-optimizer/main/install.sh | bash
```

### Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/xcalibur73/antigravity-token-optimizer/main/install.ps1 | iex
```

### Non-Destructive Backup Protection

Both `install.sh` and `install.ps1` guarantee safety through non-destructive execution:
1. Target Resolution: Defaults to `$HOME/.gemini/config/rules/AGENTS.md`, with overrides via `ANTIGRAVITY_RULES_PATH` / `AGY_RULES_PATH` (or `--target` / `-TargetRulesPath`).
2. Non-Destructive Backup: If an existing rules file is found, a timestamped backup copy (`AGENTS.md.bak.<yyyyMMdd_HHmmss>`) is created before any modifications.
3. Idempotent Invariant Injection: Scans the target file to check whether Antigravity Invariants already exist. If present, it exits cleanly without duplicating rules.
4. Automated Verification: Runs `tools/antigravity_prefix_linter.py` on the resulting rules file when Python is available.
5. Dry-Run Support: Pass `--dry-run` (`install.sh`) or `-DryRun` / `-WhatIf` (`install.ps1`) to preview actions without writing to disk.

## Core Architecture: The Antigravity Prompt Caching Engine

Gemini KV prompt caching matches byte-for-byte from the start of the prompt prefix. When an agent starts a turn and the leading tokens match a previously hashed prefix:
1. Cached tokens are served from the KV cache without recomputing activations.
2. Time-to-first-token latency drops because only the newly appended delta needs full prefill computation.

If any dynamic variable (an ISO timestamp, random session UUID, or process nonce) is inserted near the head of the system prompt or rules block, or if tool declarations are serialized in non-deterministic order, the prefix hash diverges at that byte position and the cache misses.

Antigravity Token Optimizer enforces strict prefix invariance: system instructions, tool definitions, and behavioral contracts remain static and leading, tool schemas are deterministically sorted alphabetically, and dynamic state updates are appended strictly to the tail of user turns.

## The 7 Antigravity Invariants

1. **Strict Prefix Invariance**: System instructions, tool definitions, and workspace rules remain static and leading. Dynamic turn metadata, timestamps, and request identifiers go strictly at the tail of user turns (after `<!-- DYNAMIC_TAIL -->` in templates).
2. **Subagent Context Shielding**: The coordinator acts as an orchestrator. Non-trivial tasks exceeding 50 lines of code modification, multi-file edits, or extensive exploration sweeps are delegated to isolated background subagents via `invoke_subagent`, keeping coordinator context compact (< 20,000 tokens).
3. **Head-and-Tail Terminal Stream Distillation**: Commands producing more than 30 lines of output redirect stdout and stderr to `scratch/<task>.log`. Agents inspect output via the Head-and-Tail Observation Pointer pattern (first 5 lines, clickable `file:///...` pointer URI, trailing 25 lines).
4. **Line-Bounded File Inspection**: Pass `StartLine` and `EndLine` (or equivalent line-range flags) bounded to at most 150 lines per chunk for files exceeding 150 lines.
5. **Reactive Event Scheduling**: Coordinators yield turns with zero tool calls (`tool_calls: []`) when waiting on asynchronous subagents/tasks and rely on reactive wakeups or a single `schedule` watchdog deadline rather than polling loops.
6. **Deterministic Tool Schema Ordering**: Tool schemas, function declarations, parameter properties, and `required` lists are sorted alphabetically prior to registration so prompt prefix bytes remain identical across turns and processes.
7. **Append-Only State Updates**: Never mutate historical messages or system prompts in place when working directory, permissions, or environment flags change. Append state deltas at the conversation tail.

## Measuring Real Sessions vs. Analytical Workload Simulation

### Measure Your Own Real Transcripts
Use `tools/transcript_analyzer.py` to audit real Antigravity `transcript.jsonl` logs (or Gemini API JSONL traces) for actual `promptTokenCount`, `cachedContentTokenCount`, KV cache hit rates, oversized command outputs (> 30 lines), unbounded `view_file` reads, and busy-wait polling sequences:

```bash
python tools/transcript_analyzer.py /path/to/transcript.jsonl
python tools/transcript_analyzer.py /path/to/transcript.jsonl --json
```

### Analytical Workload Simulation (`proof/benchmark_proof.py`)
`proof/benchmark_proof.py` provides a transparent, first-principles 25-turn token accounting simulation comparing:
- **Mode A (Unshielded)**: Dynamic prefix breaks KV cache on every turn (`0.0%` hit rate), full-file reads, an unredacted 20,000-line test dump, and two 6-cycle busy-wait polling loops (`1,352,000` cumulative input tokens).
- **Mode B (Invariant-Shielded)**: Static prefix + append-only deltas (`236,250` cached coordinator tokens, `15,020` uncached delta tokens, `94.0%` coordinator KV cache hit rate, `64,600` isolated subagent tokens = `315,870` total system tokens, a `76.6%` modeled raw token reduction).

Run the simulation and regenerate `proof/proof_results.json`:

```bash
python proof/benchmark_proof.py
```

```
======================================================================================================
GOOGLE ANTIGRAVITY TOKEN OPTIMIZER: ANALYTICAL WORKLOAD SIMULATION
Model Type: First-Principles 25-Turn Token Accounting (Non-Live Simulation)
======================================================================================================
Turn  Mode A Tokens   Mode B Cached   Mode B Delta  Mode B Coordinator Total   Mode B Cache Hit Rate  
------------------------------------------------------------------------------------------------------
1     5,000           0               5,000         5,000                      0.0%                   
2     18,000          5,000           400           5,400                      92.6%                  
3     26,000          5,400           450           5,850                      92.3%                  
4     34,000          5,850           400           6,250                      93.6%                  
5     185,000         6,250           500           6,750                      92.6%                  
...
24    60,000          13,970          400           14,370                     97.2%                  
25    82,000          14,370          650           15,020                     95.7%                  
------------------------------------------------------------------------------------------------------
TOTAL 1,352,000       236,250         15,020        251,270                    94.0%
======================================================================================================
```

## Setup and Usage

### Option 1: Automated Installers (Recommended)

Linux / macOS:
```bash
./install.sh --dry-run
./install.sh
./install.sh --target /custom/path/AGENTS.md
```

Windows PowerShell:
```powershell
.\install.ps1 -DryRun
.\install.ps1
.\install.ps1 -TargetRulesPath "C:\custom\path\AGENTS.md"
```

### Option 2: Repository-Level Installation
Copy `rules/AGENTS.md` to `.agents/rules/AGENTS.md` in a repository to scope the invariants per project.

### Option 3: Native Antigravity Plugin Installation
```bash
agy plugin install path/to/antigravity-token-optimizer
# Or install directly from GitHub
agy plugin install github:xcalibur73/antigravity-token-optimizer
```

## CLI Tools (Python Standard Library Only)

### 1. Antigravity Prefix Linter (`tools/antigravity_prefix_linter.py`)
Audits prompt templates, rule files, code, and tool schemas for dynamic timestamps, UUIDs, session assignments, in-place prompt mutations, unsorted tool lists, and unsorted JSON schema keys. Supports `<!-- DYNAMIC_TAIL -->` tail boundaries and `# prefix-linter: ignore` inline suppressions.

```bash
python tools/antigravity_prefix_linter.py . --strict
python tools/antigravity_prefix_linter.py rules/AGENTS.md --strict
python tools/antigravity_prefix_linter.py path/to/prompts/ --json
python tools/antigravity_prefix_linter.py . --include-tests
```

### 2. MCP Schema Compressor (`tools/mcp_schema_compressor.py`)
Enforces Invariant 6 (Deterministic Tool Schema Ordering) and prunes nulls, `$schema` boilerplate, redundant `title`s, and empty containers. **Lossless by default** (preserves full tool descriptions); pass `--condense-descriptions` to opt into single-sentence docstring condensation with constraint extraction.

```bash
# Lossless deterministic sorting + pruning with token metrics
python tools/mcp_schema_compressor.py --input schema.json --info

# Lossless in-place sort & prune
python tools/mcp_schema_compressor.py --input schema.json --in-place

# Opt-in aggressive docstring condensation + minification
python tools/mcp_schema_compressor.py --input schema.json --output minified.json --condense-descriptions --minify

# CI check mode (exits with code 1 if schema is not sorted/compressed)
python tools/mcp_schema_compressor.py --input schema.json --check
```

### 3. Transcript Analyzer (`tools/transcript_analyzer.py`)
Audits real JSONL conversation transcripts for measured `usageMetadata` cache hit rates, oversized unredacted outputs (> 30 lines), unbounded file reads, and polling loops:

```bash
python tools/transcript_analyzer.py /path/to/transcript.jsonl
python tools/transcript_analyzer.py /path/to/transcript.jsonl --json
```

### 4. Pattern Demonstrations (`examples/`)
- `python examples/reactive_watchdog_pattern.py` — Demonstrates coordinator yield + watchdog teardown.
- `powershell -ExecutionPolicy Bypass -File examples/terminal_distillation_pattern.ps1` — Demonstrates PowerShell stream redirection and Head-and-Tail pointers.

### 5. Unit Test Suite
```bash
python -m unittest discover -s tests -v
```

## Continuous Integration

`.github/workflows/ci.yml` runs across `ubuntu-latest` and `windows-latest` on Python 3.10 and 3.12:
1. Full unit test suite (`python -m unittest discover -s tests -v`), including `install.ps1` embedded rules parity verification.
2. Strict repository-wide prefix lint (`python tools/antigravity_prefix_linter.py . --strict`).
3. Workload simulation execution (`python proof/benchmark_proof.py`).
4. Dry-run validation of `install.sh --dry-run` (Ubuntu) and `install.ps1 -DryRun` (Windows).

## Repository Structure

```
antigravity-token-optimizer/
|-- .github/
|   `-- workflows/
|       `-- ci.yml                         # Multi-OS matrix CI workflow
|-- .gitignore                             # Ignores scratch, logs, and python caches
|-- LICENSE                                # MIT License
|-- README.md                              # Documentation, usage, and simulation notes
|-- install.ps1                            # Non-destructive Windows PowerShell installer
|-- install.sh                             # Non-destructive POSIX (Linux/macOS) installer
|-- plugin.json                            # Native Antigravity plugin manifest
|-- rules/
|   `-- AGENTS.md                          # Cross-platform Antigravity invariant rules
|-- skills/
|   `-- token-optimizer/
|       `-- SKILL.md                       # Antigravity skill definition
|-- proof/
|   |-- benchmark_proof.py                 # Analytical 25-turn workload simulation
|   `-- proof_results.json                 # Exported simulation data
|-- tools/
|   |-- antigravity_prefix_linter.py       # Prefix invariance & schema key ordering linter
|   |-- mcp_schema_compressor.py           # Deterministic tool schema sorter & compressor
|   `-- transcript_analyzer.py             # Real JSONL transcript & KV-cache auditor
|-- tests/
|   |-- test_prefix_linter.py              # Linter unit & regression tests
|   |-- test_repo_consistency.py           # Cross-file parity & lint cleanliness tests
|   |-- test_schema_compressor.py          # Schema compressor & CLI tests
|   `-- test_transcript_analyzer.py        # Transcript analyzer unit tests
`-- examples/
    |-- reactive_watchdog_pattern.py       # Event scheduling and watchdog pattern
    `-- terminal_distillation_pattern.ps1  # PowerShell stream redirection pattern
```

## Invariants Checklist

When configuring Antigravity agents, confirm:
1. System prompts contain zero dynamic timestamps or session identifiers.
2. Large edits and sweeps delegate to isolated background subagents.
3. Long-running terminal commands use stream redirection with the Head-and-Tail Pointer pattern (5 lines head, file pointer URI, 25 lines tail).
4. File reading calls restrict chunks to 150 lines or fewer.
5. Coordinators yield with zero tool calls and rely on reactive wakeups or a `schedule` watchdog instead of polling.
6. Tool definitions, function declarations, parameter keys, and `required` arrays are sorted alphabetically.
7. Runtime state updates and environment deltas are appended to the conversation tail rather than mutated in place.

## Contributing: Fork and Pull Requests

Contributions are welcome via forks and pull requests:
1. Fork the repository on GitHub and create a branch (`git checkout -b feature/your-optimization-name`).
2. Keep tools dependency-free (Python standard library only) and cover changes with deterministic unit tests.
3. Run the local verification battery before opening a PR:
   ```bash
   python -m unittest discover -s tests -v
   python tools/antigravity_prefix_linter.py . --strict
   bash install.sh --dry-run
   ```
4. Submit a Pull Request against `main` using conventional commit messages (`feat:`, `fix:`, `refactor:`, `docs:`).
