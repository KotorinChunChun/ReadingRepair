#requires -Version 7.0
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $root 'Install-WhisperModel.ps1')
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('ReadingRepair-setup-tests-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary|Out-Null
$passed=0
function Assert-Setup([bool]$Condition,[string]$Message){if(!$Condition){throw $Message}}
function Test-Case([string]$Name,[scriptblock]$Body){& $Body;$script:passed++;Write-Output "OK $Name"}
function Assert-Failure([scriptblock]$Body,[string]$Message){$failed=$false;try{& $Body|Out-Null}catch{$failed=$true};Assert-Setup $failed $Message}
function Assert-NoStaging([string]$Parent){Assert-Setup (@(Get-ChildItem -LiteralPath $Parent -Directory -Filter '.readingrepair-whisper-*.download').Count -eq 0) '一時フォルダーが残りました。'}
try {
    $fixture=Join-Path $temporary 'fixture'
    New-Item -ItemType Directory -Path $fixture|Out-Null
    [IO.File]::WriteAllText((Join-Path $fixture 'config.json'),'fixture-config',[Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $fixture 'model.bin'),'fixture-model',[Text.UTF8Encoding]::new($false))
    $manifest=[pscustomobject]@{source='https://example.invalid/fixture';revision='test-revision';files=@(Get-ChildItem -LiteralPath $fixture -File|ForEach-Object{[pscustomobject]@{name=$_.Name;size=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}})}
    $downloadState=[pscustomobject]@{count=0;mode='success';target=$null;requestedUris=[Collections.Generic.List[string]]::new()}
    $downloadMock={
        param($Uri,$OutFile,$TimeoutSec,$ErrorAction)
        $downloadState.count++
        if(Test-Path -LiteralPath $downloadState.target){throw '検証前に最終フォルダーが作成されました。'}
        $downloadState.requestedUris.Add($Uri)
        if($downloadState.mode -eq 'public-cli'){[IO.File]::WriteAllText($OutFile,'short fixture');return}
        if($downloadState.mode -eq 'interrupted' -and $downloadState.count -eq 2){throw 'simulated connection interruption'}
        $name=([uri]$Uri).Segments[-1]
        if($downloadState.mode -eq 'corrupt'){
            $original=[IO.File]::ReadAllBytes((Join-Path $fixture $name));$original[0]=$original[0] -bxor 1
            [IO.File]::WriteAllBytes($OutFile,$original)
        } else { Copy-Item -LiteralPath (Join-Path $fixture $name) -Destination $OutFile }
        if($downloadState.mode -eq 'racedestination' -and $downloadState.count -eq 2){
            [IO.Directory]::CreateDirectory($downloadState.target)|Out-Null
            [IO.File]::WriteAllText((Join-Path $downloadState.target 'concurrent.txt'),'created by another process')
        }
    }.GetNewClosure()
    Set-Item -Path Function:Invoke-WebRequest -Value $downloadMock
    Test-Case '全件検証後に公開する' {
        $downloadState.target=Join-Path $temporary 'success'
        $downloadState.count=0;$downloadState.mode='success'
        $result=Install-ReadingRepairVerifiedModel -Target ($downloadState.target+[IO.Path]::DirectorySeparatorChar) -Manifest $manifest
        Assert-Setup ($result.state -eq 'installed' -and $downloadState.count -eq 2) '正常取得の結果が不正です。'
        Test-ReadingRepairModelFiles -Directory $downloadState.target -Files $manifest.files
        Assert-NoStaging $temporary
    }
    Test-Case '検証済みモデルは取得・書換えしない' {
        $downloadState.target=Join-Path $temporary 'success'
        $before=Get-Item -LiteralPath (Join-Path $downloadState.target 'model.bin')
        $stamp=$before.LastWriteTimeUtc;$hash=(Get-FileHash -LiteralPath $before.FullName).Hash
        $downloadState.count=0
        $result=Install-ReadingRepairVerifiedModel -Target $downloadState.target -Manifest $manifest
        Assert-Setup ($result.state -eq 'already_exists' -and $downloadState.count -eq 0) '既存モデルを取得し直しました。'
        Assert-Setup ((Get-Item -LiteralPath $before.FullName).LastWriteTimeUtc -eq $stamp -and (Get-FileHash -LiteralPath $before.FullName).Hash -eq $hash) '既存モデルを変更しました。'
    }
    Test-Case '同サイズの破損でも公開しない' {
        $downloadState.target=Join-Path $temporary 'corrupt'
        $downloadState.count=0;$downloadState.mode='corrupt'
        Assert-Failure {Install-ReadingRepairVerifiedModel -Target $downloadState.target -Manifest $manifest} 'ハッシュ不一致を受理しました。'
        Assert-Setup (!(Test-Path -LiteralPath $downloadState.target)) '破損モデルを公開しました。'
        Assert-NoStaging $temporary
    }
    Test-Case '途中中断でも公開しない' {
        $downloadState.target=Join-Path $temporary 'interrupted'
        $downloadState.count=0;$downloadState.mode='interrupted'
        Assert-Failure {Install-ReadingRepairVerifiedModel -Target $downloadState.target -Manifest $manifest} '中断を受理しました。'
        Assert-Setup (!(Test-Path -LiteralPath $downloadState.target)) '未完了モデルを公開しました。'
        Assert-NoStaging $temporary
    }
    Test-Case '取得中に作られた保存先も上書きしない' {
        $downloadState.target=Join-Path $temporary 'concurrent'
        $downloadState.count=0;$downloadState.mode='racedestination'
        Assert-Failure {Install-ReadingRepairVerifiedModel -Target $downloadState.target -Manifest $manifest} '取得中に作られた保存先を置換しました。'
        Assert-Setup ([IO.File]::ReadAllText((Join-Path $downloadState.target 'concurrent.txt')) -eq 'created by another process') '別プロセスの内容を変更しました。'
        Assert-Setup (@(Get-ChildItem -LiteralPath $downloadState.target -Force).Count -eq 1) '別プロセスの保存先へモデルを混入しました。'
        Assert-NoStaging $temporary
    }
    Test-Case '既存の未完了フォルダーを保持する' {
        $downloadState.target=Join-Path $temporary 'incomplete'
        New-Item -ItemType Directory -Path $downloadState.target|Out-Null
        $kept=Join-Path $downloadState.target 'notes.txt';[IO.File]::WriteAllText($kept,'do not overwrite')
        $hash=(Get-FileHash -LiteralPath $kept).Hash;$stamp=(Get-Item -LiteralPath $kept).LastWriteTimeUtc
        $downloadState.count=0
        Assert-Failure {Install-ReadingRepairVerifiedModel -Target $downloadState.target -Manifest $manifest} '未完了の既存フォルダーを受理しました。'
        Assert-Setup ($downloadState.count -eq 0 -and @(Get-ChildItem -LiteralPath $downloadState.target -Force).Count -eq 1) '既存フォルダーへ取得しました。'
        Assert-Setup ((Get-FileHash -LiteralPath $kept).Hash -eq $hash -and (Get-Item -LiteralPath $kept).LastWriteTimeUtc -eq $stamp) '既存内容を変更しました。'
    }
    Test-Case '既存のファイルを保存先にしない' {
        $downloadState.target=Join-Path $temporary 'existing-file';[IO.File]::WriteAllText($downloadState.target,'keep')
        $hash=(Get-FileHash -LiteralPath $downloadState.target).Hash
        Assert-Failure {Install-ReadingRepairVerifiedModel -Target $downloadState.target -Manifest $manifest} '既存ファイルを保存先にしました。'
        Assert-Setup ((Get-FileHash -LiteralPath $downloadState.target).Hash -eq $hash) '既存ファイルを変更しました。'
    }
    Test-Case '公開CLIは固定モデルの取得へ接続する' {
        $downloadState.target=Join-Path $temporary 'public-cli';$downloadState.count=0;$downloadState.mode='public-cli'
        $downloadState.requestedUris.Clear()
        Assert-Failure {& (Join-Path $root 'Install-WhisperModel.ps1') -Destination $downloadState.target} '固定モデルのサイズ検証を迂回しました。'
        $expected=Get-ReadingRepairWhisperManifest
        Assert-Setup ($downloadState.requestedUris.Count -eq 4) "公開CLIの取得件数が不正です: $($downloadState.requestedUris.Count)"
        foreach($entry in $expected.files){Assert-Setup ($downloadState.requestedUris.Contains($expected.source+'/resolve/'+$expected.revision+'/'+$entry.name)) '公開CLIが固定リビジョンを使っていません。'}
        Assert-Setup (!(Test-Path -LiteralPath $downloadState.target)) '公開CLIが未検証モデルを公開しました。'
        Assert-NoStaging $temporary
    }
    $dictionary=Join-Path $temporary 'dictionary/new.dic'
    Test-Case '新規辞書は0バイトで作成する' {
        $result=& (Join-Path $root 'Initialize-VoisonaDictionary.ps1') -DictionaryPath $dictionary|ConvertFrom-Json
        Assert-Setup ($result.state -eq 'created' -and (Get-Item -LiteralPath $dictionary).Length -eq 0) '空辞書を作成できませんでした。'
    }
    Test-Case '既存の空辞書は変更しない' {
        $stamp=(Get-Item -LiteralPath $dictionary).LastWriteTimeUtc
        $result=& (Join-Path $root 'Initialize-VoisonaDictionary.ps1') -DictionaryPath $dictionary|ConvertFrom-Json
        Assert-Setup ($result.state -eq 'already_exists' -and (Get-Item -LiteralPath $dictionary).LastWriteTimeUtc -eq $stamp -and (Get-Item -LiteralPath $dictionary).Length -eq 0) '空辞書を変更しました。'
    }
    Test-Case '既存の非空辞書は内容と更新時刻を保持する' {
        [IO.File]::WriteAllText($dictionary,'fixture dictionary with existing content',[Text.UTF8Encoding]::new($false))
        $stamp=(Get-Item -LiteralPath $dictionary).LastWriteTimeUtc;$hash=(Get-FileHash -LiteralPath $dictionary).Hash
        $result=& (Join-Path $root 'Initialize-VoisonaDictionary.ps1') -DictionaryPath $dictionary|ConvertFrom-Json
        Assert-Setup ($result.state -eq 'already_exists' -and (Get-Item -LiteralPath $dictionary).LastWriteTimeUtc -eq $stamp -and (Get-FileHash -LiteralPath $dictionary).Hash -eq $hash) '既存辞書を変更しました。'
    }
    Test-Case '辞書へフォルダーを指定すると拒否する' {
        Assert-Failure {& (Join-Path $root 'Initialize-VoisonaDictionary.ps1') -DictionaryPath (Split-Path -Parent $dictionary)} '辞書としてフォルダーを受理しました。'
    }
    Write-Output "Setup helpers: $passed tests passed. Network and user data were not used."
}
finally {
    $cleanup=[IO.Path]::GetFullPath($temporary)
    $tempRoot=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar)+[IO.Path]::DirectorySeparatorChar
    if(!$cleanup.StartsWith($tempRoot,[StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName($cleanup) -notmatch '^ReadingRepair-setup-tests-[0-9a-f]{32}$'){throw '試験用フォルダーの削除範囲が不正です。'}
    if(Test-Path -LiteralPath $cleanup){Remove-Item -LiteralPath $cleanup -Recurse -Force}
}
