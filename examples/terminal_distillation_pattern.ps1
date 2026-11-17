# Google Antigravity Terminal Stream Distillation Pattern
# Demonstrates safe output redirection and head-and-tail pointer filtering in PowerShell.
# Prevents flooding the agent context with thousands of lines of terminal output.

[CmdletBinding()]
param(
    [string]$TaskName = "test_run",
    [string]$LogDir = "scratch"
)

$ErrorActionPreference = "Stop"

# Ensure scratch directory exists
if (-not (Test-Path -Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$LogFile = Join-Path -Path $LogDir -ChildPath "$TaskName.log"

Write-Host "============================================================"
Write-Host "Antigravity Terminal Stream Distillation Pattern"
Write-Host "============================================================"

# Simulate a command that outputs 2,000 lines of verbose build/test logs
Write-Host "[1/3] Executing build command with stream redirection..."
& {
    for ($i = 1; $i -le 2000; $i++) {
        Write-Output "[$i/2000] Compiling module component_${i} - PASS"
    }
    Write-Output "Test summary: 42 test suites executed. 42 passed, 0 failed."
    Write-Output "Build completed successfully with exit code 0."
} *> $LogFile

$ExitCode = $LASTEXITCODE
if ($null -eq $ExitCode) {
    $ExitCode = 0
}

Write-Host "[2/3] Stream captured to: $LogFile"
$TotalLines = (Get-Content -Path $LogFile | Measure-Object -Line).Lines

# Distill output: Head-and-Tail Pointer Pattern (Top 5 lines + File Pointer URI + Bottom 25 lines)
Write-Host "[3/3] Distilling terminal output (Head-and-Tail Pointer pattern)..."
$HeadLines = Get-Content -Path $LogFile -TotalCount 5
$TailLines = Get-Content -Path $LogFile -Tail 25
$FullLogPath = (Resolve-Path -Path $LogFile).Path
$FileUri = "file:///$($FullLogPath -replace '\\', '/')"

Write-Host "------------------------------------------------------------"
Write-Host "Distilled Context Block for Agent Prompt:"
Write-Host "------------------------------------------------------------"
Write-Host "[HEAD: Initialization parameters and command start]"
$HeadLines | ForEach-Object { Write-Host "  $_" }
Write-Host ""
Write-Host "[TRUNCATED: Full raw log available at: $FileUri]"
Write-Host ""
Write-Host "[TAIL: Final errors, test summaries, and exit state]"
$TailLines | ForEach-Object { Write-Host "  $_" }
Write-Host "------------------------------------------------------------"

# Compute token economy metrics
$RawTokenEstimate = [int]($TotalLines * 7.5)
$DistilledLineCount = $HeadLines.Count + $TailLines.Count + 3
$DistilledTokenEstimate = [int]($DistilledLineCount * 7.5)
$TokenSavingsPercent = [math]::Round(((1 - ($DistilledTokenEstimate / $RawTokenEstimate)) * 100), 1)

Write-Host "Token Economy Summary:"
Write-Host "  Raw Output Lines: $TotalLines lines (~$RawTokenEstimate tokens)"
Write-Host "  Distilled Context Lines: $DistilledLineCount lines (~$DistilledTokenEstimate tokens)"
Write-Host "  Context Footprint Reduction: $TokenSavingsPercent%"
Write-Host "  Full Log Pointer: $FileUri"
Write-Host "  Exit Code: $ExitCode"
Write-Host "============================================================"

exit $ExitCode
