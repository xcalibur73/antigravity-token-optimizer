# Google Antigravity Agent Constitution

This rules specification governs all Google Antigravity IDE and AGY CLI execution environments. These invariants ensure predictable execution, strict Gemini KV prompt caching integrity, and minimal token consumption.

## 1. Prompt Caching Engine and Strict Prefix Invariance

Google Antigravity relies on Gemini KV cache prefix hashing. Cache lookup matches byte-for-byte from prompt start. Any dynamic mutation at the prompt head invalidates the entire KV cache block for subsequent turns.

1. Static Prompt Head: System instructions, tool schemas, and core environment guidelines must remain static and leading. Never inject timestamps, random session tokens, process identifiers, or ephemeral UUIDs into system prompts, rule headers, or tool definitions.
2. Dynamic Metadata at Tail: Dynamic turn variables, timestamps, request identifiers, and transient parameters must be placed strictly at the tail of user messages.
3. Cache Compaction Discipline: Plan context compaction when conversation context reaches 100,000 tokens or when major operational phases complete. Maintain static prefix anchors across conversation boundaries.

## 2. Subagent Context Shielding

Coordinators must remain high-level orchestrators. Flooding coordinator context with extensive code diffs or multi-file refactoring runs destroys context space and drives token consumption.

1. Delegation Threshold: Non-trivial code modifications (more than 50 lines on a single file, multi-file code modifications, and heavy exploration sweeps) must be delegated to background subagents using invoke_subagent.
2. Coordinator Context Budget: Keep coordinator context under 20,000 tokens. The coordinator delegates implementation, reviews isolated diffs, runs independent verification, and records high-level outcomes.
3. Isolated Worker Execution: Subagents execute in isolated context windows. Heavy multi-turn trial loops run inside worker context, shielding the coordinator from prompt explosion.
4. Structured Return Payload: Workers summarize their findings and return concise receipts through send_message. The coordinator ingests the summary without replaying intermediate worker tool traces.

## 3. Terminal Stream Distillation

Raw terminal output from builds, test runners, and package managers often spans hundreds or thousands of lines. Flooding agent context with verbose terminal streams exhausts token quotas within minutes.

1. Redirection Requirement: Any command expected to generate more than 30 lines of terminal output must redirect stdout and stderr to scratch/<task>.log.
2. Tail and Filter Inspection: Inspect log files using targeted PowerShell commands, specifically Get-Content -Tail 30 or Select-String filters.
3. Token Economy Target: Distill command feedback from 150,000 raw log tokens down to approximately 300 actionable tokens covering status, exit code, and terminal error traces.

## 4. Line-Bounded File Inspection

Reading entire source files into context wastes input bandwidth and evicts relevant instructions from prompt attention.

1. Bounded Chunk Size: Always pass StartLine and EndLine when inspecting files exceeding 150 lines. Restrict inspection windows to at most 150 lines per tool call.
2. Target Verification: Identify line targets using search tools or structural references before issuing targeted read calls.
3. Full-File Exemption: Full-file inspection is permitted only when executing complete structural rewrites of compact modules under 150 lines.

## 5. Reactive Event Scheduling and Watchdog Invariant

Antigravity subagents and background tasks run asynchronously. Coordinators must never run busy-wait polling loops.

1. Zero Busy-Wait Polling: Coordinators must never issue repeated status polling calls (such as polling manage_subagents every few seconds) or tail transcript files during wait intervals.
2. Mechanical Turn Yield: Immediately after dispatching subagents or background tasks, the coordinator must yield execution with zero tool calls. Antigravity resumes execution reactively when send_message delivers incoming payloads.
3. Mandatory Watchdog Deadline: To guard against hung workers or silent exits, arm a single global watchdog deadline before yielding: schedule(DurationSeconds=300..600, Prompt="Watchdog: task timed out", TimerCondition="never").
4. Quorum and Teardown: When all subagents complete, cancel the active watchdog timer using manage_task(Action="kill", TaskId=<timer_id>) before continuing synthesis.

## 6. Windows PowerShell Runtime Safety

Windows environments require strict execution discipline to prevent encoding corruptions and quote escaping failures.

1. Zero Shell CD Commands: Never run cd in terminal calls. Always specify absolute paths or explicit working directories.
2. Zero Multi-Line Inline Python: Multi-line inline Python scripts executed via python -c in PowerShell cause escaping crashes. All execution scripts must be written to standalone Python files in scratch/ and executed directly.
3. Explicit UTF-8 Encoding: Every Python file open, read, or write operation must explicitly declare encoding="utf-8" to prevent character corruption.

## 7. Anti-Cheating and Code Quality Invariants

1. Zero Assertion Dilution: Never weaken, relax, or broaden assertion thresholds or expected values just to force a failing test to pass. If an assertion fails, the implementation must be fixed, not the test contract.
2. Zero Test Tampering: Never delete, skip, comment out, or bypass failing test cases or test files to fake a passing suite.
3. Zero Fake or Placeholder Logic: Never commit hollow stub implementations, fake return literals, dummy mocks in production code paths, or unfulfilled TODO and FIXME comments.
4. Zero Type Evasion: Never suppress type errors with bypass flags or silent catches.
5. Standard Library First: Leverage language standard libraries and built-in capabilities before introducing third-party packages.
