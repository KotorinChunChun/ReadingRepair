#requires -Version 7.0
param([string]$OutputRoot=(Join-Path $PSScriptRoot '../release'))
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$releaseRoot=[IO.Path]::GetFullPath($OutputRoot)
$buildId=Get-Date -Format 'yyyyMMdd-HHmmss'
$stage=Join-Path $releaseRoot ('build-'+$buildId)
$bundle=Join-Path $stage 'ReadingRepair'
if(Test-Path -LiteralPath $stage){throw '新しい配布先を指定してください。'}
[IO.Directory]::CreateDirectory($bundle)|Out-Null
$python=Join-Path $root '.venv/Scripts/python.exe'
$env:PYTHONUTF8='1'
& $python -m PyInstaller --noconfirm --clean --name ReadingRepair.Backend --onedir --console --distpath (Join-Path $stage 'python-dist') --workpath (Join-Path $stage 'python-build') --specpath $stage --paths (Join-Path $root 'backend') --collect-all faster_whisper --collect-all ctranslate2 --collect-all tokenizers --collect-all onnxruntime --collect-all av --copy-metadata huggingface-hub --copy-metadata faster-whisper (Join-Path $root 'backend/application.py')
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
Copy-Item -LiteralPath (Join-Path $stage 'python-dist/ReadingRepair.Backend') -Destination (Join-Path $bundle 'backend') -Recurse
foreach($file in @('Invoke-LabLlm.ps1','CodexClient.psm1')){Copy-Item -LiteralPath (Join-Path $root ('backend/'+$file)) -Destination (Join-Path $bundle 'backend')}
dotnet publish (Join-Path $root 'Desktop/ReadingRepair.Desktop.csproj') -c Release -r win-x64 --self-contained true -p:NuGetAudit=false -o $bundle --nologo
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
dotnet publish (Join-Path $root 'Registration/Registration.csproj') -c Release -r win-x64 --self-contained true -p:NuGetAudit=false -o (Join-Path $bundle 'registration') --nologo
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
foreach($file in @('LICENSE','THIRD-PARTY-NOTICES.md','Invoke-ReadingRepair.ps1','Start-ReadingRepair.ps1','tts.env.example','reviewers.env.example','sample.txt','requirements-build.txt','tool.json')){Copy-Item -LiteralPath (Join-Path $root $file) -Destination $bundle}
$definition=Get-Content -LiteralPath (Join-Path $bundle 'tool.json') -Raw|ConvertFrom-Json
$definition.executable='ReadingRepair.exe'
$definition|ConvertTo-Json -Depth 10|Set-Content -LiteralPath (Join-Path $bundle 'tool.json') -Encoding utf8
& (Join-Path $PSScriptRoot 'Copy-SetupAssets.ps1') -Destination $bundle
& $python (Join-Path $root 'scripts/collect_licenses.py') $bundle
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
# 配布物からしか起動しない。利用者のデータは参照しないversion照合。
$version=& (Join-Path $bundle 'backend/ReadingRepair.Backend.exe') version
if($LASTEXITCODE -ne 0 -or ($version|ConvertFrom-Json).result.version -ne '0.0.1'){throw '同梱backendのバージョンを確認できません。'}
$archive=Join-Path $releaseRoot 'ReadingRepair-v0.0.1-win-x64.zip'
if(Test-Path -LiteralPath $archive){throw '既存の配布ZIPは上書きしません。'}
Compress-Archive -Path $bundle -DestinationPath $archive -CompressionLevel Optimal
$hash=(Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
$hash+'  '+[IO.Path]::GetFileName($archive)|Set-Content -LiteralPath (Join-Path $releaseRoot 'SHA256SUMS.txt') -Encoding utf8
@{version='0.0.1';bundle=$bundle;archive=$archive;sha256=$hash}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $releaseRoot 'build-result.json') -Encoding utf8
Get-Content -LiteralPath (Join-Path $releaseRoot 'build-result.json')
