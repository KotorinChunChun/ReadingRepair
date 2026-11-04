#requires -Version 7.0
param([string]$Output=(Join-Path $PSScriptRoot ('../dev/history/v0.0.1/logs/dictionary-gui-sync-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[guid]::NewGuid().ToString('N').Substring(0,8))))
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$out=[IO.Path]::GetFullPath($Output)
if(Test-Path -LiteralPath $out){throw '新しい隔離出力先を指定してください。'}
[IO.Directory]::CreateDirectory($out)|Out-Null
dotnet build (Join-Path $root 'Desktop.SyncTests/Desktop.SyncTests.csproj') -p:NuGetAudit=false --nologo
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
& (Join-Path $root 'Desktop.SyncTests/bin/Debug/net10.0-windows/Desktop.SyncTests.exe') --workspace $root --settings (Join-Path $out 'settings.json') *> (Join-Path $out 'result.log')
$code=$LASTEXITCODE
Get-Content -LiteralPath (Join-Path $out 'result.log')
exit $code
