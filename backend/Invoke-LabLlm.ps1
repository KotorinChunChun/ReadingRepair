#requires -Version 7.0
param([Parameter(Mandatory)][string]$PromptFile,[Parameter(Mandatory)][string]$OutputFile,[string]$Model='gpt-5.6-luna')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Import-Module (Join-Path $PSScriptRoot 'CodexClient.psm1') -Force
$prompt=[IO.File]::ReadAllText($PromptFile,[Text.Encoding]::UTF8)
$reply=Invoke-CodexReply -Prompt $prompt -Model $Model -TimeoutSeconds 180
[IO.File]::WriteAllText($OutputFile,$reply,[Text.UTF8Encoding]::new($false))
