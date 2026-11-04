#requires -Version 7.0
[CmdletBinding()]
param(
    [string]$Destination=(Join-Path $env:LOCALAPPDATA 'ReadingRepair/models/faster-whisper-small')
)
$ErrorActionPreference='Stop'

function Get-ReadingRepairWhisperManifest {
    [pscustomobject]@{
        source='https://huggingface.co/Systran/faster-whisper-small'
        revision='536b0662742c02347bc0e980a01041f333bce120'
        files=@(
            [pscustomobject]@{name='config.json';size=2370L;sha256='b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828'},
            [pscustomobject]@{name='model.bin';size=483546902L;sha256='3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671'},
            [pscustomobject]@{name='tokenizer.json';size=2203239L;sha256='fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab'},
            [pscustomobject]@{name='vocabulary.txt';size=459861L;sha256='34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913'}
        )
    }
}

function Test-ReadingRepairModelFiles {
    param([Parameter(Mandatory)][string]$Directory,[Parameter(Mandatory)][object[]]$Files)
    foreach($entry in $Files){
        $file=Join-Path $Directory $entry.name
        if(!(Test-Path -LiteralPath $file -PathType Leaf)){throw "モデルファイルがありません: $($entry.name)"}
        if((Get-Item -LiteralPath $file).Length -ne $entry.size){throw "モデルファイルのサイズが一致しません: $($entry.name)"}
        if((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ine $entry.sha256){throw "モデルファイルのSHA-256が一致しません: $($entry.name)"}
    }
}

function Install-ReadingRepairVerifiedModel {
    param([Parameter(Mandatory)][string]$Target,[Parameter(Mandatory)][object]$Manifest)
    $resolved=[IO.Path]::TrimEndingDirectorySeparator([IO.Path]::GetFullPath($Target))
    $parent=[IO.Path]::GetDirectoryName($resolved)
    if(!$parent -or ![IO.Path]::GetFileName($resolved)){throw 'モデルの保存先フォルダーを指定してください。'}
    $files=@($Manifest.files)
    if(!$files.Count){throw 'モデルファイルの定義が空です。'}
    $names=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach($entry in $files){
        if([string]::IsNullOrWhiteSpace($entry.name) -or [IO.Path]::GetFileName($entry.name) -ne $entry.name -or $entry.name -in @('.','..') -or !$names.Add($entry.name)){
            throw 'モデルファイル名の定義が不正です。'
        }
    }
    if(Test-Path -LiteralPath $resolved){
        if(!(Test-Path -LiteralPath $resolved -PathType Container)){throw '保存先には既にファイルがあります。別のフォルダーを指定してください。'}
        try { Test-ReadingRepairModelFiles -Directory $resolved -Files $files }
        catch { throw '保存先のモデルが未完了または定義と異なります。既存内容は変更しません。別の保存先を指定してください。' }
        return [pscustomobject]@{state='already_exists';path=$resolved;source=$Manifest.source;revision=$Manifest.revision;files=$files.Count}
    }
    [IO.Directory]::CreateDirectory($parent)|Out-Null
    $staging=Join-Path $parent ('.readingrepair-whisper-'+[guid]::NewGuid().ToString('N')+'.download')
    $created=$false
    try {
        New-Item -ItemType Directory -Path $staging -ErrorAction Stop|Out-Null
        $created=$true
        $ProgressPreference='SilentlyContinue'
        foreach($entry in $files){
            $uri=$Manifest.source+'/resolve/'+$Manifest.revision+'/'+$entry.name
            try { Invoke-WebRequest -Uri $uri -OutFile (Join-Path $staging $entry.name) -TimeoutSec 900 -ErrorAction Stop|Out-Null }
            catch { throw "モデルファイルを取得できません: $($entry.name)。通信を確認して再実行してください。" }
        }
        Test-ReadingRepairModelFiles -Directory $staging -Files $files
        # 全件検証前には保存先を作らず、同時に作られた保存先も上書きしない。
        [IO.Directory]::Move($staging,$resolved)
        $created=$false
        return [pscustomobject]@{state='installed';path=$resolved;source=$Manifest.source;revision=$Manifest.revision;files=$files.Count}
    }
    finally {
        if($created -and (Test-Path -LiteralPath $staging)){
            $cleanup=[IO.Path]::GetFullPath($staging)
            if([IO.Path]::GetDirectoryName($cleanup) -ne $parent -or [IO.Path]::GetFileName($cleanup) -notmatch '^\.readingrepair-whisper-[0-9a-f]{32}\.download$'){
                throw '一時フォルダーの削除範囲を確認できません。'
            }
            Remove-Item -LiteralPath $cleanup -Recurse -Force
        }
    }
}

if($MyInvocation.InvocationName -ne '.'){
    Install-ReadingRepairVerifiedModel -Target $Destination -Manifest (Get-ReadingRepairWhisperManifest)|ConvertTo-Json -Depth 4
}
