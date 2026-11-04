#requires -Version 7.0
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$copy=Join-Path $PSScriptRoot 'Copy-SetupAssets.ps1'
$rootFiles=@('README.md','Install-WhisperModel.ps1','Initialize-VoisonaDictionary.ps1')
$expected=@($rootFiles)+@(Get-ChildItem -LiteralPath (Join-Path $root 'docs') -Recurse -File |
    ForEach-Object {[IO.Path]::GetRelativePath($root,$_.FullName)})
$tempBase=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\','/')
$temp=Join-Path $tempBase ('ReadingRepair-setup-assets-'+[guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temp)|Out-Null
$passed=0

function Assert-Assets([string]$Source,[string]$Payload){
    foreach($relative in $expected){
        $actual=Join-Path $Payload $relative
        if(!(Test-Path -LiteralPath $actual -PathType Leaf)){throw ('同梱漏れ: '+$relative)}
        if((Get-FileHash -LiteralPath $actual).Hash -ne (Get-FileHash -LiteralPath (Join-Path $Source $relative)).Hash){
            throw ('内容が一致しません: '+$relative)
        }
    }
}

try {
    # 各配布スクリプトが共通コピー処理へ渡すpayloadを確認する。
    foreach($build in @(@{name='Build-Release.ps1';variable='bundle'},@{name='Build-Installer.ps1';variable='payload'})){
        $tokens=$null;$errors=$null
        $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $build.name),[ref]$tokens,[ref]$errors)
        if($errors.Count){throw ('PowerShell構文エラー: '+$build.name)}
        $calls=@($ast.FindAll({param($node)
            $node -is [Management.Automation.Language.CommandAst] -and
            $node.InvocationOperator -eq [Management.Automation.Language.TokenKind]::Ampersand -and
            $node.Extent.Text -match 'Copy-SetupAssets\.ps1'
        },$true))
        if($calls.Count -ne 1){throw ('共通コピー処理の呼出しが一意ではありません: '+$build.name)}
        $elements=$calls[0].CommandElements
        $destination=@($elements | Where-Object {$_ -is [Management.Automation.Language.CommandParameterAst] -and $_.ParameterName -eq 'Destination'})
        if($destination.Count -ne 1){throw ('共通コピー先がありません: '+$build.name)}
        $argument=$elements[$elements.IndexOf($destination[0])+1]
        if($argument -isnot [Management.Automation.Language.VariableExpressionAst] -or $argument.VariablePath.UserPath -ne $build.variable){
            throw ('共通コピー先が不正です: '+$build.name)
        }
    }
    $passed++

    # 新規ZIP向けpayloadは、許可リストの資料だけになる。
    $portable=Join-Path $temp 'portable/ReadingRepair'
    & $copy -Destination $portable
    Assert-Assets $root $portable
    if(@(Get-ChildItem -LiteralPath $portable -Recurse -File).Count -ne $expected.Count){throw 'ZIP向けpayloadに許可リスト外のファイルがあります。'}
    $passed++

    # 固定ZIPを展開したsetup向けpayloadでは、旧資料を更新し本体は保持する。
    $installer=Join-Path $temp 'installer/ReadingRepair'
    [IO.Directory]::CreateDirectory((Join-Path $installer 'docs'))|Out-Null
    Set-Content -LiteralPath (Join-Path $installer 'docs/guide.md') -Value '旧説明書' -Encoding utf8
    $binary=Join-Path $installer 'ReadingRepair.exe'
    [IO.File]::WriteAllBytes($binary,[byte[]](1,2,3,4))
    $binaryHash=(Get-FileHash -LiteralPath $binary).Hash
    & $copy -Destination $installer
    Assert-Assets $root $installer
    if((Get-FileHash -LiteralPath $binary).Hash -ne $binaryHash){throw '既存の本体を変更しました。'}
    $passed++

    # 実処理を別の最小ソース配置でも実行し、秘密・実行結果の非同梱を確認する。
    $fixture=Join-Path $temp 'source'
    [IO.Directory]::CreateDirectory((Join-Path $fixture 'scripts'))|Out-Null
    Copy-Item -LiteralPath $copy -Destination (Join-Path $fixture 'scripts/Copy-SetupAssets.ps1')
    foreach($relative in $expected){
        $output=Join-Path $fixture $relative
        [IO.Directory]::CreateDirectory((Split-Path -Parent $output))|Out-Null
        Copy-Item -LiteralPath (Join-Path $root $relative) -Destination $output
    }
    foreach($relative in @('tts.env','runs/input.txt','models/model.bin','user_dict_ja_jp.dic','private.wav')){
        $output=Join-Path $fixture $relative
        [IO.Directory]::CreateDirectory((Split-Path -Parent $output))|Out-Null
        Set-Content -LiteralPath $output -Value '同梱しない試験データ' -Encoding utf8
    }
    $fixturePayload=Join-Path $temp 'fixture-payload'
    & (Join-Path $fixture 'scripts/Copy-SetupAssets.ps1') -Destination $fixturePayload
    Assert-Assets $fixture $fixturePayload
    if(@(Get-ChildItem -LiteralPath $fixturePayload -Recurse -File).Count -ne $expected.Count){throw '許可リスト外の秘密・実行結果をコピーしました。'}
    $passed++

    # 入力が不足する場合は、出力先も作らずに停止する。
    $missing=Join-Path $fixture 'Initialize-VoisonaDictionary.ps1'
    if(!( [IO.Path]::GetFullPath($missing).StartsWith($temp+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase))){throw '試験領域外の削除を拒否しました。'}
    Remove-Item -LiteralPath $missing
    $incomplete=Join-Path $temp 'incomplete-payload'
    $failed=$false
    try { & (Join-Path $fixture 'scripts/Copy-SetupAssets.ps1') -Destination $incomplete }
    catch { $failed=$true }
    if(!$failed -or (Test-Path -LiteralPath $incomplete)){throw '入力欠落時に部分的なpayloadを作りました。'}
    $passed++

    [ordered]@{passed=$passed;rootFiles=$rootFiles;documentationFiles=$expected.Count-$rootFiles.Count;fullBuild=$false}|ConvertTo-Json
}
finally {
    $resolved=[IO.Path]::GetFullPath($temp)
    if((Split-Path -Parent $resolved) -eq $tempBase -and (Split-Path -Leaf $resolved) -match '^ReadingRepair-setup-assets-[0-9a-f]{32}$'){
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
