param(
    [string]$UserMessage = "",
    [int]$DelaySeconds = 2,
    [switch]$LiveCognee,
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendDir = Join-Path $RepoRoot "backend"
$AssetsDir = Join-Path $RepoRoot "docs\assets"
$RawTranscript = Join-Path $AssetsDir "codex-terminal-raw.txt"
$CodexLastMessage = Join-Path $BackendDir "codex_live_last_message.txt"
$HindsightJson = Join-Path $AssetsDir "codex-hindsight-check.json"

function Pause-ForReplay {
    if ($DelaySeconds -gt 0) {
        Start-Sleep -Seconds $DelaySeconds
    }
}

function Add-RawLine {
    param([string]$Text)
    Add-Content -Path $RawTranscript -Value $Text -Encoding utf8
}

New-Item -ItemType Directory -Force $AssetsDir | Out-Null

if (-not $KeepArtifacts) {
    Remove-Item -Force $RawTranscript, $CodexLastMessage, $HindsightJson -ErrorAction SilentlyContinue
}

if ([string]::IsNullOrWhiteSpace($UserMessage)) {
    $UserMessage = Read-Host "User message for Codex"
}

if ([string]::IsNullOrWhiteSpace($UserMessage)) {
    throw "User message cannot be empty."
}

Set-Location $RepoRoot

Write-Host "user" -ForegroundColor Cyan
Write-Host $UserMessage -ForegroundColor White
Pause-ForReplay

$codexCommand = "codex exec --color never -s read-only -C . --output-last-message backend\codex_live_last_message.txt `"$UserMessage`""
Write-Host ""
Write-Host "PS $RepoRoot> $codexCommand" -ForegroundColor Green
Add-RawLine "PS $RepoRoot> $codexCommand"

& codex exec --color never -s read-only -C . --output-last-message $CodexLastMessage $UserMessage 2>&1 | Tee-Object -FilePath $RawTranscript -Append

Pause-ForReplay

Set-Location $BackendDir
if (-not $LiveCognee) {
    .\.venv\Scripts\python.exe -c "from app.service import activate_demo_mode; activate_demo_mode()" | Out-Null
}

$hindsightCommand = ".\.venv\Scripts\python.exe -m app.codex_session --file codex_live_last_message.txt --session-id codex-live-terminal-proof --event-type agent_memory_write --source-label codex-terminal-replay"
Write-Host ""
Write-Host "PS $BackendDir> $hindsightCommand" -ForegroundColor Green
Add-RawLine ""
Add-RawLine "PS $BackendDir> $hindsightCommand"

& .\.venv\Scripts\python.exe -m app.codex_session --file codex_live_last_message.txt --session-id codex-live-terminal-proof --event-type agent_memory_write --source-label codex-terminal-replay 2>&1 | Tee-Object -FilePath $HindsightJson | Tee-Object -FilePath $RawTranscript -Append

Set-Location $RepoRoot

Write-Host ""
Write-Host "Artifacts" -ForegroundColor Cyan
Write-Host "- $RawTranscript" -ForegroundColor Gray
Write-Host "- $HindsightJson" -ForegroundColor Gray