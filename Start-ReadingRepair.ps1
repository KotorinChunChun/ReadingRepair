#requires -Version 7.0
param([string]$SettingsFile, [switch]$NoBuild)
$ErrorActionPreference='Stop'
$workspace=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if(!$NoBuild){
    dotnet build (Join-Path $PSScriptRoot 'Registration/Registration.csproj') -p:NuGetAudit=false --nologo
    if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
    dotnet build (Join-Path $PSScriptRoot 'Desktop/ReadingRepair.Desktop.csproj') -p:NuGetAudit=false --nologo
    if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
}
$app=Join-Path $PSScriptRoot 'Desktop/bin/ReadingRepair/Debug/net10.0-windows/VoisonaReadingRepair.exe'
if(!(Test-Path -LiteralPath $app)){throw 'アプリを先にビルドしてください。'}
$arguments=@('--workspace',$workspace)
if($SettingsFile){$arguments+=@('--settings',[IO.Path]::GetFullPath($SettingsFile))}
# UIを操作するためのアプリ起動。通常のバックグラウンドヘルパーとは別に表示する。
Start-Process -FilePath $app -ArgumentList ($arguments | ForEach-Object {'"'+$_+'"'}) -WindowStyle Normal
