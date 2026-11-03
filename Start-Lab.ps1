#requires -Version 7.0
param(
    [Parameter(Mandatory)][string]$ProjectRoot,
    [string]$TextFile = (Join-Path $PSScriptRoot 'sample.txt'),
    [string]$RunDirectory,
    [string]$Python = (Join-Path $env:LOCALAPPDATA 'Programs/Python/Python312/python.exe'),
    [string]$WhisperSitePackages,
    [string]$ReviewerEnv = 'C:\AI\env\voisona-reading-review.env',
    [string]$AnswersFile,
    [switch]$RetryReviewers,
    [switch]$Apply,
    [switch]$PrepareOnly,
    [switch]$Resume
)
$ErrorActionPreference = 'Stop'
if (!$RunDirectory) {
    $workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
    $RunDirectory = Join-Path $workspace ('dev/history/v0.4.0/logs/dictionary-lab-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
$env:PYTHONIOENCODING = 'utf-8'
$arguments = @((Join-Path $PSScriptRoot 'lab.py'), '--project-root', $ProjectRoot, '--text-file', $TextFile, '--run-dir', $RunDirectory)
$arguments += @('--reviewer-env', $ReviewerEnv)
if ($AnswersFile) { $arguments += @('--answers-file', $AnswersFile) }
if ($RetryReviewers) { $arguments += '--retry-reviewers' }
if ($WhisperSitePackages) { $arguments += @('--whisper-site-packages', $WhisperSitePackages) }
if ($Apply) { $arguments += '--apply' }
if ($PrepareOnly) { $arguments += '--prepare-only' }
if ($Resume) { $arguments += '--resume' }
& $Python @arguments
exit $LASTEXITCODE
