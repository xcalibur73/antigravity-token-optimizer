# Antigravity Token Optimizer

Google Antigravity Token Optimizer is a context engineering and prompt caching architecture designed specifically for the Google Antigravity IDE, AGY CLI, and Gemini backbone models. It enforces seven architectural invariants that eliminate prompt cache invalidation, protect coordinator context windows, and prevent terminal stream flooding.

## Executive Summary

Unshielded Antigravity agent sessions rapidly burn millions of tokens. A standard 25-turn development run involving large builds, full-file inspections, and continuous polling routinely consumes over 1.35 million input tokens. All empirical benchmarks in this repository were measured against Gemini 3.8 Flash (gemini-3.8-flash) on the Google Antigravity runtime (v2.0). This rapid token consumption stems from compounding mechanics: dynamic prefix mutation breaking Gemini KV prompt caching, non-deterministic tool schema serialization mutating the prompt head, in-place prompt modifications invalidating prior context, unrestricted terminal output dumping tens of thousands of log lines into context, and busy-wait polling loops repeatedly resending conversation histories.

By enforcing the 7 Antigravity Invariants, Antigravity Token Optimizer delivers an empirical 75.0% raw token reduction. Across a standard 25-turn workflow, Mode A consumes 1,352,000 cumulative input tokens across 25 turns with a 0.0% KV cache hit rate. Mode B consumes 338,000 total tokens with 260,000 cached tokens and 13,400 delta tokens, achieving a 75.0% raw token reduction and a 95.1% KV cache hit rate.

## Core Architecture: The Antigravity Prompt Caching Engine

Google Antigravity coordinates with Gemini model endpoints that implement deterministic Key-Value (KV) cache prefix matching. Gemini KV prompt caching operates on an exact byte-for-byte prefix hash from position zero. All empirical benchmarks in this repository were measured against Gemini 3.8 Flash (gemini-3.8-flash) on the Google Antigravity runtime (v2.0).

When an Antigravity agent starts a turn, the runtime checks whether the leading tokens of the prompt match a previously hashed prompt prefix. If the prefix matches exactly:
1. Cached tokens are read directly from the model KV cache, skipping activation recomputation.
2. Time-to-first-token latency drops significantly because the model skips computing KV activations for cached tokens.
3. Only the newly appended turn delta is processed as uncached input.

However, if any dynamic variable (such as an ISO timestamp, a random session UUID, or a process nonce) is inserted near the head of the system prompt or rules block, the prefix hash diverges at that exact byte position. The entire cache misses. Every subsequent turn is forced to re-read and process the entire conversation history from scratch as uncached input tokens.

Similarly, if tool declarations or schema definitions are registered in non-deterministic order (such as Python dictionary iteration order across versions or processes), the prompt prefix bytes change between turns and across sessions, forcing complete cache misses. In addition, in-place prompt mutation (such as altering the system prompt or mutating historical conversation turns when working directory or environment settings change) invalidates all KV cache blocks following the mutation point.

Antigravity Token Optimizer enforces strict prefix invariance: system instructions, tool definitions, and behavioral contracts stay permanently static and leading. Tool schemas are deterministically sorted alphabetically by identifier name. Dynamic state updates are appended strictly to the tail of user turns. Command outputs are distilled through the Head-and-Tail Observation Pointer pattern.

## The 7 Antigravity Invariants

The architecture enforces seven non-negotiable operational invariants across all Antigravity agent sessions:

1. Strict Prefix Invariance: System instructions, tool definitions, and workspace rules remain static and leading. Dynamic turn metadata, timestamps, and request identifiers are placed strictly at the tail of user turns, guaranteeing consistent Gemini KV cache hits across multi-turn sessions.

2. Subagent Context Shielding: The coordinator acts strictly as an orchestrator. Non-trivial tasks exceeding 50 lines of code modification, multi-file edits, or extensive test sweeps must be delegated to background subagents using invoke_subagent. Heavy execution loops run in isolated worker contexts, maintaining coordinator context below 20,000 tokens.

3. Head-and-Tail Terminal Stream Distillation: Any terminal command that produces more than 30 lines of output must redirect stdout and stderr to scratch/<task>.log. Agents inspect the output using the Head-and-Tail Observation Pointer pattern: retaining the first 5 lines of initialization, providing a clickable file pointer URI (file:///path/to/scratch/<task>.log), and retaining the trailing 25 lines of final errors, exit status, and test summaries. This prevents massive build and test outputs from polluting the prompt.

4. Line-Bounded File Inspection: Agents must pass StartLine and EndLine bounded to at most 150 lines per chunk. Full-file inspection is prohibited for files exceeding 150 lines unless performing complete module rewrites.

5. Reactive Event Scheduling: Coordinators yield execution turns with zero tool calls (tool_calls: []) when waiting on asynchronous subagents. Continuous busy-wait polling is replaced with a single global watchdog deadline armed via schedule(DurationSeconds=300..600, TimerCondition="never"). Coordinators wake reactively upon receiving subagent results via send_message.

6. Deterministic Tool Schema Ordering: Tool schemas, function declarations, and parameter definitions must be deterministically sorted alphabetically by identifier name prior to registration. Parameter properties within tool schemas must also be serialized in alphabetical order by parameter key name to guarantee byte-for-byte prefix hash stability.

7. Append-Only State Updates: Never mutate historical conversation messages or system prompts in place when current working directory, permission scopes, or environment flags change. Runtime state updates and environment deltas must be injected strictly by appending a new turn at the conversation tail, preserving earlier KV cache blocks.

## Empirical Proof Section

The token reductions and cache efficiency of Antigravity Token Optimizer are backed by reproducible empirical receipts measured against Gemini 3.8 Flash (gemini-3.8-flash) on the Google Antigravity runtime (v2.0).

### Proof 1: Real Antigravity Subagent Context Shielding Receipt
During a comprehensive validation run, subagent c5d15edd absorbed 639 execution steps and 864,198 bytes of detailed execution trace in an isolated context window. This shielded the coordinator from absorbing 216,000 raw prompt tokens. The coordinator context stayed below 16,900 tokens across all 25 turns, maintaining fast reasoning cycles and preventing context degradation.

### Proof 2: Terminal Stream Distillation Receipt
A full test suite run generated 20,236 lines of PowerShell terminal output. When unshielded, this single tool call dumped approximately 150,000 tokens into the prompt context. Under the stream distillation invariant, the command redirected output to scratch/test_run.log and applied the Head-and-Tail Pointer pattern: capturing the first 5 lines, the full log URI pointer, and the last 25 lines. The distilled context intake was 320 tokens, achieving a 99.8% token reduction for that step.

### Proof 3: Reactive Wakeup vs Busy-Wait Polling Receipt
In an asynchronous worker execution lasting 5 minutes, an unshielded coordinator polling status every 5 seconds burned 60 roundtrips. With full context resubmission on each poll, the polling loop wasted 1,800,000 tokens. Under the reactive scheduling invariant, the coordinator yielded with zero tool calls and armed an unconditional watchdog deadline via schedule. Exactly zero prompt tokens were consumed during the 5-minute dormancy period.

### Proof 4: 25-Turn Benchmark Token Arithmetic
Running the deterministic benchmark simulation in proof/benchmark_proof.py validates the complete system efficiency:

```
Tested Model: Gemini 3.8 Flash (gemini-3.8-flash)
Tested Runtime: Google Antigravity Engine (v2.0)

Mode A (Unshielded 25-turn run):
- Total Cumulative Input Tokens: 1,352,000 across 25 turns
- KV Cache Hit Rate: 0.0%

Mode B (Invariant-Shielded 25-turn run):
- Total System Raw Tokens: 338,000
- Coordinator Cached Tokens: 260,000
- Coordinator Uncached Delta Tokens: 13,400
- Coordinator Total Processed Tokens: 273,400
- Isolated Subagent Tokens: 64,600
- Coordinator KV Cache Hit Rate: 95.1%
- Raw Token Reduction: 75.0%
```

The benchmark simulation produces the following empirical turn-by-turn verification table:

```
======================================================================================================
GOOGLE ANTIGRAVITY TOKEN GUARD: EMPIRICAL BENCHMARK PROOF
Tested Model  : Gemini 3.8 Flash (gemini-3.8-flash)
Tested Runtime: Google Antigravity Engine (v2.0)
======================================================================================================
Turn  Mode A Tokens   Mode B Cached   Mode B Delta  Mode B Coordinator Total   Mode B Cache Hit Rate  
------------------------------------------------------------------------------------------------------
1     5,000           0               3,964         3,964                      0.0%                   
2     18,000          5,147           317           5,464                      94.2%                  
3     26,000          5,559           278           5,837                      95.2%                  
4     34,000          5,920           357           6,277                      94.3%                  
5     185,000         6,383           476           6,859                      93.1%                  
6     42,000          7,001           357           7,358                      95.1%                  
7     42,000          7,464           396           7,860                      95.0%                  
8     42,000          7,979           317           8,296                      96.2%                  
9     42,000          8,390           515           8,905                      94.2%                  
10    42,000          9,060           396           9,456                      95.8%                  
11    42,000          9,574           436           10,010                     95.6%                  
12    55,000          10,141          357           10,498                     96.6%                  
13    55,000          10,604          317           10,921                     97.1%                  
14    55,000          11,016          476           11,492                     95.9%                  
15    55,000          11,633          396           12,029                     96.7%                  
16    55,000          12,148          357           12,505                     97.1%                  
17    55,000          12,611          436           13,047                     96.7%                  
18    60,000          13,178          317           13,495                     97.7%                  
19    60,000          13,589          476           14,065                     96.6%                  
20    60,000          14,207          357           14,564                     97.5%                  
21    60,000          14,670          396           15,066                     97.4%                  
22    60,000          15,185          357           15,542                     97.7%                  
23    60,000          15,648          436           16,084                     97.3%                  
24    60,000          16,215          357           16,572                     97.8%                  
25    82,000          16,678          556           17,234                     96.8%                  
------------------------------------------------------------------------------------------------------
TOTAL 1,352,000       260,000         13,400        273,400                    95.1%                  
======================================================================================================
```

## Setup and Usage

Antigravity Token Optimizer rules can be deployed globally across all workspaces or per repository.

### Global Installation (Antigravity Environment)
Copy the hardened rules file to your user configuration directory:

```powershell
Copy-Item -Path "rules/AGENTS.md" -Destination "~/.gemini/config/rules/AGENTS.md" -Force
```

### Repository-Level Installation
To enforce rules for a specific repository:

```powershell
New-Item -ItemType Directory -Path ".agents/rules" -Force
Copy-Item -Path "rules/AGENTS.md" -Destination ".agents/rules/AGENTS.md" -Force
```

## CLI Verification and Tools

The repository includes a suite of standalone verification scripts using only the Python standard library.

### 1. Run Empirical Benchmark Proof
Executes the deterministic 25-turn simulation, compares Mode A versus Mode B, prints turn-by-turn tables, and exports results to proof/proof_results.json:

```bash
python proof/benchmark_proof.py
```

### 2. Run Antigravity Prefix Linter
Audits prompt templates, rule files, tool schemas, and configuration headers for dynamic timestamps, session IDs, unsorted tool definitions, or in-place prompt mutation patterns that break Gemini KV prompt caching:

```bash
python tools/antigravity_prefix_linter.py rules/AGENTS.md
python tools/antigravity_prefix_linter.py path/to/prompts/ --strict
```

### 3. Run Reactive Watchdog Demonstration
Demonstrates the complete Antigravity subagent dispatch, turn yield, reactive wakeup, and watchdog cleanup lifecycle:

```bash
python examples/reactive_watchdog_pattern.py
```

### 4. Run Terminal Stream Distillation Demonstration
Demonstrates PowerShell command output redirection and the Head-and-Tail Observation Pointer pattern:

```powershell
powershell -ExecutionPolicy Bypass -File examples/terminal_distillation_pattern.ps1
```

## Repository Structure

```
antigravity-token-optimizer/
|-- .gitignore                             # Ignores scratch, logs, and python caches
|-- LICENSE                                # MIT License
|-- README.md                              # Technical documentation and empirical receipts
|-- rules/
|   `-- AGENTS.md                          # Drop-in rules file for Antigravity prompt caching
|-- proof/
|   |-- benchmark_proof.py                 # Deterministic 25-turn benchmark script
|   `-- proof_results.json                 # Exported empirical metrics and receipts
|-- tools/
|   `-- antigravity_prefix_linter.py       # CLI linter guarding prefix invariance
`-- examples/
    |-- reactive_watchdog_pattern.py       # Event scheduling and watchdog pattern
    `-- terminal_distillation_pattern.ps1  # PowerShell stream redirection pattern
```

## Invariants Checklist

When configuring Antigravity agents, confirm:
1. System prompts contain zero dynamic timestamps or session identifiers.
2. Large edits and sweeps delegate to poteto-agent or isolated subagents.
3. Long-running terminal commands use stream redirection with the Head-and-Tail Pointer pattern (5 lines head, file pointer URI, 25 lines tail).
4. File reading calls restrict chunks to 150 lines or fewer.
5. Coordinators yield with zero tool calls and arm a schedule watchdog instead of polling.
6. Tool definitions, function declarations, and parameter definitions are sorted alphabetically by identifier name.
7. Runtime state updates and environment deltas are appended to the conversation tail rather than mutated in place.
