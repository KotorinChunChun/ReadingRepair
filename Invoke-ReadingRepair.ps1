#requires -Version 7.0
param(
    [Parameter(Position=0)][ValidateSet('doctor','settings','save-settings','create','execute','status','history','answer','stop','audio','export','dictionary','check-dictionary','add-dictionary','log','llm-log')][string]$Command='doctor',
    [string]$Job,
    [string]$TextFile,
    [string]$RequestFile,
    [string]$SettingsFile,
    [ValidateSet('repair','verify')][string]$Mode='repair',
    [ValidateSet('before','after')][string]$Phase='after',
    [string]$Python=(Join-Path $env:LOCALAPPDATA 'Programs/Python/Python312/python.exe'),
    [switch]$Build,
    [switch]$Apply,
    [switch]$RetryReviewers,
    [switch]$Play
)
$ErrorActionPreference='Stop'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
if($Build){
    foreach($project in @('Registration/Registration.csproj','Desktop/ReadingRepair.Desktop.csproj')){
        dotnet build (Join-Path $PSScriptRoot $project) -p:NuGetAudit=false --nologo
        if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
    }
}
if($Command -in @('execute','status','answer','stop','audio','export','log','llm-log') -and !$Job){throw '実行IDを-Jobで指定してください。'}
$arguments=@((Join-Path $PSScriptRoot 'application.py'),$Command)
if($Job){$arguments+=@('--job',$Job)}
if($TextFile){$arguments+=@('--text-file',[IO.Path]::GetFullPath($TextFile),'--mode',$Mode)}
if($RequestFile){$arguments+=@('--request',[IO.Path]::GetFullPath($RequestFile))}
if($SettingsFile){$arguments+=@('--settings',[IO.Path]::GetFullPath($SettingsFile))}
if($RetryReviewers){$arguments+='--retry-reviewers'}
if($Apply){$arguments+='--apply'}
if($Command -eq 'audio'){$arguments+=@('--phase',$Phase)}
if($Play){$arguments+='--play'}
& $Python @arguments
exit $LASTEXITCODE
