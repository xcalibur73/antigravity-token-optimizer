# Antigravity Token Optimizer - One-Line Automated Installer
# Target: Windows PowerShell 5.1+ and PowerShell 7+
# Usage:
#   Local:   .\install.ps1 [-TargetRulesPath <path>] [-DryRun] [-WhatIf]
#   Remote:  irm https://raw.githubusercontent.com/xcalibur73/antigravity-token-optimizer/main/install.ps1 | iex

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$TargetRulesPath = "",

    [Parameter(Mandatory = $false)]
    [switch]$WhatIf,

    [Parameter(Mandatory = $false)]
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if ($DryRun) {
    $WhatIf = $true
}

# -----------------------------------------------------------------------------
# Embedded Production Invariants Fallback
# -----------------------------------------------------------------------------
$EmbeddedRules = @'
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

## 3. Head-and-Tail Terminal Stream Distillation

Raw terminal output from builds, test runners, and package managers often spans hundreds or thousands of lines. Flooding agent context with verbose terminal streams exhausts token quotas within minutes.

1. Redirection Requirement: Any command expected to generate more than 30 lines of terminal output must redirect stdout and stderr to scratch/<task>.log.
2. Head-and-Tail Observation Pointer Pattern: Construct prompt observations using the Head-and-Tail Pointer structure: capture the first 5 lines of output (initialization and command start), provide a clickable file pointer URI (file:///path/to/scratch/<task>.log) for full inspection, and capture the trailing 25 lines of output (final errors, exit state, and test summaries).
3. Token Economy Target: Distill command feedback from 150,000 raw log tokens down to approximately 300 actionable tokens covering status, exit code, and terminal error traces without losing essential failure diagnostics.

## 4. Line-Bounded File Inspection

Reading entire source files into context wastes input bandwidth and evicts relevant instructions from prompt attention.

1. Bounded Chunk Size: Always pass StartLine and EndLine when inspecting files exceeding 150 lines. Restrict inspection windows to at most 150 lines per tool call.
2. Target Verification: Identify line targets using search tools or structural references before issuing targeted read calls.
3. Full-File Exemption: Full-file inspection is permitted only when executing complete structural rewrites of compact modules under 150 lines.

## 5. Reactive Event Scheduling and Watchdog Invariant

Antigravity subagents and background tasks run asynchronously. Coordinators must never run busy-wait polling loops.

1. Zero Busy-Wait Polling: Coordinators must never issue repeated status polling calls (such as polling manage_subagents every few seconds) or tail transcript files during wait intervals.
2. Mechanical Turn Yield: Immediately after dispatching subagents or background tasks, the coordinator must yield execution with zero tool calls. Antigravity resumes execution reactively when send_message delivers incoming payloads.
3. Mandatory Watchdog Deadline: To guard against hung workers or silent exits, arm a single global watchdog deadline before yielding: schedule(DurationSeconds=300..600, Prompt="Watchdog: subagents timed out", TimerCondition="never"). Incremental completions wake the coordinator reactively without cancelling the timer.
4. Quorum Teardown Protocol: When all subagents complete, cancel the watchdog deadline with manage_task(Action="kill", TaskId=<timer_task_id>) before synthesizing outcomes.

## 6. Deterministic Tool Schema Ordering

Tool declarations and schemas are registered at the prompt head. Non-deterministic dictionary iteration or random registration ordering alters prefix byte sequences and causes Gemini KV cache misses.

1. Alphabetical Sorting Requirement: Tool schemas, function declarations, and parameter definitions must be deterministically sorted alphabetically by identifier name prior to registration to ensure identical byte-for-byte prefix hashing.
2. Schema Property Ordering: Parameter properties within each tool schema object must be serialized in alphabetical order by parameter key name to guarantee byte-for-byte prefix hash stability.
3. Static Registration Order: Once sorted, tool definitions must remain in identical sequence across all turns and subagent invocations within the session.

## 7. Append-Only State Updates

Agent environments encounter dynamic changes such as directory navigation, credential refreshes, or configuration adjustments. Modifying earlier context turns destroys prefix caching.

1. Zero In-Place Mutation: Never mutate historical conversation messages or system prompts in place when current working directory, permission sets, or environment flags change.
2. Tail-Appended Runtime Deltas: Inject all state updates, working directory changes, and runtime notices strictly by appending a new turn at the conversation tail.
3. Cache Stability Guarantee: Appending state changes to the tail preserves the entire leading KV cache prefix, allowing previous turn tokens to remain cached while only billing the newly appended state delta.

## 8. Windows PowerShell Runtime Safety

Windows environments require strict execution discipline to prevent encoding corruptions and quote escaping failures.

1. Zero Shell CD Commands: Never run cd in terminal calls. Always specify absolute paths or explicit working directories.
2. Zero Multi-Line Inline Python: Multi-line inline Python scripts executed via python -c in PowerShell cause escaping crashes. All execution scripts must be written to standalone Python files in scratch/ and executed directly.
3. Explicit UTF-8 Encoding: Every Python file open, read, or write operation must explicitly declare encoding="utf-8" to prevent character corruption.

## 9. Anti-Cheating and Code Quality Invariants

1. Zero Assertion Dilution: Never weaken, relax, or broaden assertion thresholds or expected values just to force a failing test to pass. If an assertion fails, the implementation must be fixed, not the test contract.
2. Zero Test Tampering: Never delete, skip, comment out, or bypass failing test cases or test files to fake a passing suite.
3. Zero Fake or Placeholder Logic: Never commit hollow stub implementations, fake return literals, dummy mocks in production code paths, or unfulfilled TODO and FIXME comments.
4. Zero Type Evasion: Never suppress type errors with bypass flags or silent catches.
5. Standard Library First: Leverage language standard libraries and built-in capabilities before introducing third-party packages.
'@

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------
function Get-ProductionRules {
    param([string]$ScriptDir)

    if ($ScriptDir -and (Test-Path -Path (Join-Path $ScriptDir "rules\AGENTS.md"))) {
        $path = Join-Path $ScriptDir "rules\AGENTS.md"
        return [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
    }

    if (Test-Path -Path "rules\AGENTS.md") {
        return [System.IO.File]::ReadAllText("rules\AGENTS.md", [System.Text.Encoding]::UTF8)
    }

    $remoteUrl = "https://raw.githubusercontent.com/xcalibur73/antigravity-token-optimizer/main/rules/AGENTS.md"
    try {
        $webClient = New-Object System.Net.WebClient
        $webClient.Encoding = [System.Text.Encoding]::UTF8
        $downloaded = $webClient.DownloadString($remoteUrl)
        if ($downloaded -and $downloaded.Length -gt 100) {
            return $downloaded
        }
    } catch {
        # Fallback to embedded string if network is unreachable
    }

    return $EmbeddedRules
}

function Locate-PrefixLinter {
    param([string]$ScriptDir)

    if ($ScriptDir -and (Test-Path -Path (Join-Path $ScriptDir "tools\antigravity_prefix_linter.py"))) {
        return (Join-Path $ScriptDir "tools\antigravity_prefix_linter.py")
    }

    if (Test-Path -Path "tools\antigravity_prefix_linter.py") {
        return (Resolve-Path "tools\antigravity_prefix_linter.py").Path
    }

    $parentPath = Join-Path $ScriptDir "..\tools\antigravity_prefix_linter.py"
    if ($ScriptDir -and (Test-Path -Path $parentPath)) {
        return (Resolve-Path $parentPath).Path
    }

    $tempLinter = Join-Path $env:TEMP "antigravity_prefix_linter.py"
    $remoteUrl = "https://raw.githubusercontent.com/xcalibur73/antigravity-token-optimizer/main/tools/antigravity_prefix_linter.py"
    try {
        $webClient = New-Object System.Net.WebClient
        $webClient.Encoding = [System.Text.Encoding]::UTF8
        $webClient.DownloadFile($remoteUrl, $tempLinter)
        if (Test-Path -Path $tempLinter) {
            return $tempLinter
        }
    } catch {
        # Download skipped if unreachable
    }

    return $null
}

# -----------------------------------------------------------------------------
# Main Execution Flow
# -----------------------------------------------------------------------------
Write-Host "=================================================="
Write-Host "Antigravity Token Optimizer: Automated Installer"
Write-Host "=================================================="

$scriptDir = $PSScriptRoot
if (-not $scriptDir -and $MyInvocation.MyCommand.Path) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}

# Step 1: Target Resolution
$target = $TargetRulesPath
if ([string]::IsNullOrWhiteSpace($target)) {
    if (-not [string]::IsNullOrWhiteSpace($env:ANTIGRAVITY_RULES_PATH)) {
        $target = $env:ANTIGRAVITY_RULES_PATH
    } elseif (-not [string]::IsNullOrWhiteSpace($env:AGY_RULES_PATH)) {
        $target = $env:AGY_RULES_PATH
    } else {
        $target = [System.IO.Path]::Combine($HOME, ".gemini", "config", "rules", "AGENTS.md")
    }
}

$resolvedTarget = [System.IO.Path]::GetFullPath($target)
$targetDirectory = [System.IO.Path]::GetDirectoryName($resolvedTarget)
Write-Host "Target configuration path: $resolvedTarget"

if (-not (Test-Path -Path $targetDirectory)) {
    if ($WhatIf) {
        Write-Host "[WHAT-IF] Would create directory: $targetDirectory"
    } else {
        [System.IO.Directory]::CreateDirectory($targetDirectory) | Out-Null
        Write-Host "Created target directory: $targetDirectory"
    }
}

# Step 2: Invariant Check & Non-Destructive Backup
$rulesToAdd = Get-ProductionRules -ScriptDir $scriptDir
$targetExists = Test-Path -Path $resolvedTarget -PathType Leaf

if ($targetExists) {
    $existingText = [System.IO.File]::ReadAllText($resolvedTarget, [System.Text.Encoding]::UTF8)
    $hasInvariants = $existingText.Contains("Prompt Caching Engine and Strict Prefix Invariance") -or $existingText.Contains("Google Antigravity Agent Constitution")
    
    if ($hasInvariants) {
        Write-Host "Status: Target rules file already contains Antigravity Invariants."
        Write-Host "Action: System is already optimized. Exiting cleanly without modification."
        
        # Verify linter on existing file
        $linter = Locate-PrefixLinter -ScriptDir $scriptDir
        $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
        if ($linter -and $pythonCmd) {
            Write-Host "Running prefix linter audit..."
            $lintOutput = & python $linter $resolvedTarget 2>&1
            if ($LASTEXITCODE -ne 0) {
                Write-Error "Prefix linter audit failed with exit code $($LASTEXITCODE):`n$lintOutput"
                exit $LASTEXITCODE
            }
            Write-Host "Verification result: PASSED (exit code 0)."
        }
        Write-Host "=================================================="
        return
    }

    # Backup existing file before modification
    $timestamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
    $backupPath = "$resolvedTarget.bak.$timestamp"
    if (Test-Path -Path $backupPath) {
        $backupPath = "$resolvedTarget.bak.${timestamp}_1"
    }

    if ($WhatIf) {
        Write-Host "[WHAT-IF] Existing rules file detected. Would create backup copy: $backupPath"
        Write-Host "[WHAT-IF] Would append Antigravity Invariants to: $resolvedTarget"
    } else {
        Copy-Item -Path $resolvedTarget -Destination $backupPath -Force
        Write-Host "Non-destructive backup created: $backupPath"

        # Cleanly append invariants
        $trimmedExisting = $existingText.TrimEnd()
        $updatedText = $trimmedExisting + [System.Environment]::NewLine + [System.Environment]::NewLine + $rulesToAdd.Trim() + [System.Environment]::NewLine
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($resolvedTarget, $updatedText, $utf8NoBom)
        Write-Host "Injected Antigravity Token Optimizer invariants into: $resolvedTarget"
    }
} else {
    # Target does not exist yet
    if ($WhatIf) {
        Write-Host "[WHAT-IF] Target file does not exist. Would write new invariants to: $resolvedTarget"
    } else {
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($resolvedTarget, $rulesToAdd.Trim() + [System.Environment]::NewLine, $utf8NoBom)
        Write-Host "Created rules file with Antigravity Token Optimizer invariants: $resolvedTarget"
    }
}

# Step 3: Verification Audit
if ($WhatIf) {
    Write-Host "[WHAT-IF] Dry run completed successfully. Zero changes committed."
    Write-Host "=================================================="
    return
}

$linterPath = Locate-PrefixLinter -ScriptDir $scriptDir
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($linterPath -and $pythonCmd) {
    Write-Host "Running prefix linter audit..."
    $lintOutput = & python $linterPath $resolvedTarget 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Prefix linter audit failed with exit code $($LASTEXITCODE):`n$lintOutput"
        exit $LASTEXITCODE
    }
    Write-Host "Verification result: PASSED (exit code 0)."
} else {
    Write-Host "Note: Python or prefix linter not available in current environment; skipped linter verification."
}

Write-Host "Optimization complete: Antigravity Token Optimizer is active."
Write-Host "=================================================="
