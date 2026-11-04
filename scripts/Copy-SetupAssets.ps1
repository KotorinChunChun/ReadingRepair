#requires -Version 7.0
param([Parameter(Mandatory)][string]$Destination)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$target=[IO.Path]::GetFullPath($Destination)
$rootFiles=@('README.md','Install-WhisperModel.ps1','Initialize-VoisonaDictionary.ps1')
$requiredDocs=@('docs/guide.md','docs/development.md','docs/first-run.md','docs/tts-engines.md')

# ZIPと既存ZIPを入力にするsetupで、同じ導入資料を使う。
# 欠落時に途中まで配置しないよう、すべての入力をコピー前に確認する。
foreach($relative in @($rootFiles)+$requiredDocs){
    if(!(Test-Path -LiteralPath (Join-Path $root $relative) -PathType Leaf)){
        throw ('導入資料の入力がありません: '+$relative)
    }
}
$files=@($rootFiles)+@(Get-ChildItem -LiteralPath (Join-Path $root 'docs') -Recurse -File |
    Sort-Object FullName | ForEach-Object {[IO.Path]::GetRelativePath($root,$_.FullName)})

# ルート全体はコピーせず、許可した補助とdocsだけを配置する。
foreach($relative in $files){
    $output=Join-Path $target $relative
    [IO.Directory]::CreateDirectory((Split-Path -Parent $output))|Out-Null
    Copy-Item -LiteralPath (Join-Path $root $relative) -Destination $output -Force
}
Write-Verbose ('初回導入資料'+$files.Count+'件を配置しました: '+$target)
