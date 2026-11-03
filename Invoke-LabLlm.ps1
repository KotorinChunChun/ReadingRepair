#requires -Version 7.0
param(
    [Parameter(Mandatory)][string]$ProjectRoot,
    [Parameter(Mandatory)][string]$PromptFile,
    [Parameter(Mandatory)][string]$OutputFile,
    [string]$Model = 'gpt-5.6-luna'
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Import-Module (Join-Path $ProjectRoot 'src/CodexChat.psm1') -Force
# 本体の会話ログ設定をこの検証プロセスへ持ち込まない。
$env:VOISONA_LLM_LOG_PATH = ''
$env:VOISONA_LLM_LOG_WARNING_PATH = ''
$prompt = [IO.File]::ReadAllText($PromptFile, [Text.Encoding]::UTF8)
$reply = Invoke-CodexReply -Prompt $prompt -Model $Model -TimeoutSeconds 180
[IO.File]::WriteAllText($OutputFile, $reply, [Text.UTF8Encoding]::new($false))
