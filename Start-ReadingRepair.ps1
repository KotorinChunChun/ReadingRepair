#requires -Version 7.0
param([string]$SettingsFile,[switch]$NoBuild)
$ErrorActionPreference='Stop'
$app=Join-Path $PSScriptRoot 'ReadingRepair.exe'
if(!(Test-Path -LiteralPath $app)) {
    if(!$NoBuild){
        foreach($project in @('Registration/Registration.csproj','Desktop/ReadingRepair.Desktop.csproj')){
            dotnet build (Join-Path $PSScriptRoot $project) -p:NuGetAudit=false --nologo
            if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
        }
    }
    $app=Join-Path $PSScriptRoot 'Desktop/bin/Debug/net10.0-windows/ReadingRepair.exe'
}
if(!(Test-Path -LiteralPath $app)){throw 'アプリをビルドするか配布版を展開してください。'}
$arguments=@('--workspace',$PSScriptRoot)
if($SettingsFile){$arguments+=@('--settings',[IO.Path]::GetFullPath($SettingsFile))}
Start-Process -FilePath $app -ArgumentList ($arguments | ForEach-Object {'"'+$_+'"'}) -WindowStyle Normal
