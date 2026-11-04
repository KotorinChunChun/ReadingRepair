#requires -Version 7.0
param(
    [Parameter(Mandatory)][string]$PortableArchive,
    [Parameter(Mandatory)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ExpectedArchiveSha256,
    [Parameter(Mandatory)][string]$MaintenanceDirectory,
    [Parameter(Mandatory)][string]$Compiler,
    [Parameter(Mandatory)][string]$ApplicationDirectory,
    [Parameter(Mandatory)][string]$RegistrationDirectory,
    [string]$OutputRoot=(Join-Path $PSScriptRoot '../release/installer')
)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$archive=[IO.Path]::GetFullPath($PortableArchive)
$maintenance=[IO.Path]::GetFullPath($MaintenanceDirectory)
$compilerPath=[IO.Path]::GetFullPath($Compiler)
$expected=$ExpectedArchiveSha256.ToLowerInvariant()
$productVersion=(Get-Content -LiteralPath (Join-Path $root 'tool.json') -Raw|ConvertFrom-Json).version
if($productVersion -notmatch '^\d+\.\d+\.\d+$'){throw '製品版は3桁の数値版が必要です。'}
if((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected){throw '採用したZIPと固定ハッシュが一致しません。'}
foreach($name in @('KotorinToys.Maintenance.exe','coreclr.dll','hostfxr.dll','hostpolicy.dll')){
    if(!(Test-Path -LiteralPath (Join-Path $maintenance $name))){throw '自己完結型の共通Maintenanceを指定してください。'}
}
if((Get-AuthenticodeSignature -LiteralPath $compilerPath).Status -ne 'Valid'){throw 'Innoコンパイラーの署名を確認できません。'}
$stage=Join-Path ([IO.Path]::GetFullPath($OutputRoot)) ('build-'+[guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($stage)|Out-Null
$zip=[IO.Compression.ZipFile]::OpenRead($archive)
try {
    foreach($entry in $zip.Entries){
        $relative=$entry.FullName.Replace('\','/')
        if(!$relative.StartsWith('ReadingRepair/') -or $relative -match '(^|/)\.\.(/|$)' -or $relative.Contains(':') -or (($entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000){throw 'ZIPに範囲外参照またはリンクがあります。'}
    }
}finally{$zip.Dispose()}
Expand-Archive -LiteralPath $archive -DestinationPath $stage
$payload=Join-Path $stage 'ReadingRepair'
$backendVersion=& (Join-Path $payload 'backend/ReadingRepair.Backend.exe') version
if($LASTEXITCODE -ne 0 -or ($backendVersion|ConvertFrom-Json).result.version -ne $productVersion){throw 'ZIP内backendの製品版が一致しません。'}
$payloadPrefix=[IO.Path]::GetFullPath($payload)+[IO.Path]::DirectorySeparatorChar
# 新規に展開した候補のデバッグ情報だけを除外する。
foreach($file in Get-ChildItem -LiteralPath $payload -Recurse -File -Filter '*.pdb'){
    if(!$file.FullName.StartsWith($payloadPrefix,[StringComparison]::OrdinalIgnoreCase)){throw '出力外の削除を拒否しました。'}
    Remove-Item -LiteralPath $file.FullName
}
# 同じ採用ソースから発行した.NET入力と、検証済みランタイムを照合する。
foreach($item in @(@{directory=$ApplicationDirectory;name='ReadingRepair'},@{directory=$RegistrationDirectory;name='ReadingRepair.Registration'})){
    $config=Get-Content -LiteralPath (Join-Path $item.directory ($item.name+'.runtimeconfig.json')) -Raw|ConvertFrom-Json
    if(@($config.runtimeOptions.includedFrameworks|Where-Object version -ne '10.0.14').Count){throw '同梱ランタイムは検証した10.0.14が必要です。'}
}
Copy-Item -Path (Join-Path ([IO.Path]::GetFullPath($ApplicationDirectory)) '*') -Destination $payload -Recurse -Force
Copy-Item -Path (Join-Path ([IO.Path]::GetFullPath($RegistrationDirectory)) '*') -Destination (Join-Path $payload 'registration') -Recurse -Force
$definition=Get-Content -LiteralPath (Join-Path $root 'tool.json') -Raw|ConvertFrom-Json
if($definition.name -ne 'ReadingRepair' -or $definition.version -ne $productVersion -or $definition.appId -ne 'KotorinToys.ReadingRepair'){throw '製品定義が一致しません。'}
$definition.executable='ReadingRepair.exe'
$definition.distributionStatus='published'
$definition|ConvertTo-Json -Depth 12|Set-Content -LiteralPath (Join-Path $payload 'tool.json') -Encoding utf8
& (Join-Path $PSScriptRoot 'Copy-SetupAssets.ps1') -Destination $payload
Copy-Item -LiteralPath $maintenance -Destination (Join-Path $payload 'maintenance') -Recurse
# ONNXの形状推論・量子化などの開発ツールは音声認識に使用しない。
# 実行モジュールとVADモデルを残し、不要なソース配布を避ける。
$developmentTools=[IO.Path]::GetFullPath((Join-Path $payload 'backend/_internal/onnxruntime/tools'))
if(!$developmentTools.StartsWith($payloadPrefix,[StringComparison]::OrdinalIgnoreCase)){throw '出力外の削除を拒否しました。'}
if(Test-Path -LiteralPath $developmentTools){Remove-Item -LiteralPath $developmentTools -Recurse}
# 同梱したランタイムに対応するライセンスと通知を集約する。
$nugetRoot=if($env:NUGET_PACKAGES){$env:NUGET_PACKAGES}else{Join-Path $env:USERPROFILE '.nuget/packages'}
foreach($config in Get-ChildItem -LiteralPath $payload -Recurse -File -Filter '*.runtimeconfig.json'){
    $options=(Get-Content -LiteralPath $config.FullName -Raw|ConvertFrom-Json).runtimeOptions
    foreach($framework in $options.includedFrameworks){
        $packageId=$framework.name.ToLowerInvariant()+'.runtime.win-x64'
        $package=Join-Path $nugetRoot ($packageId+'/'+$framework.version)
        $licenses=@(Get-ChildItem -LiteralPath $package -File|Where-Object Name -Match '^(LICENSE|THIRD-PARTY-NOTICES)(\.TXT)?$')
        if(!$licenses.Count){throw 'ランタイムのライセンスを確認できません。'}
        $target=Join-Path $payload ('runtime-licenses/'+$framework.name+'/'+$framework.version)
        [IO.Directory]::CreateDirectory($target)|Out-Null
        foreach($license in $licenses){Copy-Item -LiteralPath $license.FullName -Destination $target -Force}
    }
}
$info=[Diagnostics.FileVersionInfo]::GetVersionInfo((Join-Path $payload 'ReadingRepair.exe'))
if($info.ProductName -ne 'ReadingRepair' -or "$($info.FileMajorPart).$($info.FileMinorPart).$($info.FileBuildPart)" -ne $productVersion){throw 'EXEの製品名・版が不正です。'}
$before=@(Get-ChildItem -LiteralPath $payload -Recurse -File|ForEach-Object {
    [ordered]@{path=[IO.Path]::GetRelativePath($payload,$_.FullName).Replace('\','/');length=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
})
[ordered]@{sourceArchiveSha256=$expected;files=$before}|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $stage 'payload-files.json') -Encoding utf8
& $compilerPath --quiet-progress '--define=ProductName=ReadingRepair' '--define=ProductAppId=KotorinToys.ReadingRepair' "--define=ProductVersion=$productVersion" "--define=Payload=$payload" "--define=OutputDirectory=$stage" (Join-Path $root 'installer/product.iss')
if($LASTEXITCODE -ne 0){throw 'インストーラー生成に失敗しました。'}
$file='ReadingRepair-'+$productVersion+'-setup.exe'
$setup=Join-Path $stage $file
$sha=(Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
$package=[ordered]@{id='reading-repair';name='ReadingRepair';version=$productVersion;appId='KotorinToys.ReadingRepair';file=$file;sha256=$sha;signature='unsigned-public-build';kind='inno'}
[ordered]@{schemaVersion=1;distributionStatus='published';packages=@($package)}|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $stage 'ReadingRepair-packages.json') -Encoding utf8
($sha+'  '+$file)|Set-Content -LiteralPath (Join-Path $stage 'ReadingRepair-SHA256SUMS.txt') -Encoding utf8
$result=[ordered]@{version=$productVersion;directory=$stage;payload=$payload;installer=$setup;sha256=$sha;bytes=(Get-Item -LiteralPath $setup).Length;sourceArchiveSha256=$expected}
$result|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $stage 'build-result.json') -Encoding utf8
$result|ConvertTo-Json|Set-Content -LiteralPath (Join-Path ([IO.Path]::GetFullPath($OutputRoot)) 'latest-build.json') -Encoding utf8
$result|ConvertTo-Json
