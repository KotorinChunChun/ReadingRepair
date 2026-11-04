#requires -Version 7.0
param(
    [string]$Workspace=(Join-Path $PSScriptRoot '..'),
    [string]$PythonExecutable=(Join-Path $PSScriptRoot '../.venv/Scripts/python.exe'),
    [string]$DesktopAssembly,
    [string]$Output=(Join-Path $PSScriptRoot ('../dev/history/v0.0.3/logs/dictionary-gui-sync-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[guid]::NewGuid().ToString('N').Substring(0,8))))
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$out=[IO.Path]::GetFullPath($Output)
if(Test-Path -LiteralPath $out){throw '新しい隔離出力先を指定してください。'}
[IO.Directory]::CreateDirectory($out)|Out-Null
dotnet build (Join-Path $root 'Desktop.SyncTests/Desktop.SyncTests.csproj') -p:NuGetAudit=false --nologo
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
if($DesktopAssembly){Copy-Item -LiteralPath $DesktopAssembly -Destination (Join-Path $root 'Desktop.SyncTests/bin/Debug/net10.0-windows/ReadingRepair.dll') -Force}
& (Join-Path $root 'Desktop.SyncTests/bin/Debug/net10.0-windows/Desktop.SyncTests.exe') --workspace ([IO.Path]::GetFullPath($Workspace)) --python ([IO.Path]::GetFullPath($PythonExecutable)) --lock-backend (Join-Path $root 'backend') --settings (Join-Path $out 'settings.json') *> (Join-Path $out 'result.log')
$code=$LASTEXITCODE
Get-Content -LiteralPath (Join-Path $out 'result.log')
exit $code
