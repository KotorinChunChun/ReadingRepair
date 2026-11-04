#requires -Version 7.0
[CmdletBinding()]
param(
    [string]$DictionaryPath=(Join-Path $env:APPDATA 'Techno-Speech/VoiSona Talk/Talker/user_dict_ja_jp.dic')
)
$ErrorActionPreference='Stop'
$resolved=[IO.Path]::GetFullPath($DictionaryPath)
if(Test-Path -LiteralPath $resolved){
    if(!(Test-Path -LiteralPath $resolved -PathType Leaf)){throw '辞書の保存先はフォルダーではなくファイルで指定してください。'}
    [pscustomobject]@{state='already_exists';path=$resolved;bytes=(Get-Item -LiteralPath $resolved).Length}|ConvertTo-Json
    return
}
$parent=[IO.Path]::GetDirectoryName($resolved)
if(!$parent -or ![IO.Path]::GetFileName($resolved)){throw '辞書ファイルの保存先を指定してください。'}
[IO.Directory]::CreateDirectory($parent)|Out-Null
# CreateNewは、確認後に別プロセスが作成した辞書も置換しない。
$stream=[IO.File]::Open($resolved,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
try { $stream.Flush() }
finally { $stream.Dispose() }
[pscustomobject]@{state='created';path=$resolved;bytes=0}|ConvertTo-Json
