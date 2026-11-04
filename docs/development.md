# 開発・検証・配布

## 開発起動

Python 3.12、.NET 10 SDK、PowerShell 7を使用します。旧VoisonaTalkAIやKotorinToys親のソースはビルド依存ではありません。

```powershell
Set-Location '<ReadingRepairのチェックアウト先>'
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-build.txt
./Start-ReadingRepair.ps1
```

## 検証

```powershell
$env:PYTHONUTF8='1'
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('ReadingRepair-regression-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$previousLocal = $env:LOCALAPPDATA
$previousRoaming = $env:APPDATA
try {
    $env:LOCALAPPDATA = Join-Path $testRoot 'Local'
    $env:APPDATA = Join-Path $testRoot 'Roaming'
    ./.venv/Scripts/python.exe -B -m unittest discover -s backend -p 'test_*.py' -q
    if ($LASTEXITCODE -ne 0) { throw 'バックエンド回帰が失敗しました。' }
}
finally {
    $env:LOCALAPPDATA = $previousLocal
    $env:APPDATA = $previousRoaming
    $resolved = [IO.Path]::GetFullPath($testRoot)
    $temporary = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\', '/')
    if ((Split-Path -Parent $resolved) -eq $temporary -and
        (Split-Path -Leaf $resolved) -match '^ReadingRepair-regression-[0-9a-f]{32}$') {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
```

一部の回帰試験はアプリのロック保存先を使うため、通常利用のLocalAppDataではなく一時領域へ分離して実行します。.NET側の検証は.NET 10 SDKがある開発環境で行います。

```powershell
dotnet build Desktop/ReadingRepair.Desktop.csproj -p:NuGetAudit=false
dotnet build Registration/Registration.csproj -p:NuGetAudit=false
./Registration/bin/Debug/net10.0-windows/ReadingRepair.Registration.exe self-test
./scripts/Test-Desktop.ps1
```

HTTP TTS試験はローカルサーバーで実POST/WAVを使い、認識とLLMは架空応答です。実辞書へは登録しません。VoiSona接続・本物のWhisper・実音声の確認は別の実接続試験として記録します。

faster-whisper 1.2.1はPyAV 19で廃止された引数を使うため、本版は検証したPyAVを固定します。[上流の報告](https://github.com/SYSTRAN/faster-whisper/issues/1589)とローカル実測を版別報告へ記録します。

## 配布

```powershell
./scripts/Build-Release.ps1
```

専用の新規出力フォルダーへ.NET自己完結win-x64版、PyInstallerのPython backend、一次LLM呼出し用PowerShell、説明書、空設定例、ライセンスを許可リストで配置します。モデル・利用者設定・原文・辞書・ログ・キーを含めません。ZIPとSHA-256はreleaseへ出力し、版別logsへ検証結果を保存します。

初回導入の資料・補助スクリプトは`Copy-SetupAssets.ps1`の共通コピー経路からZIPとsetupの両payloadへ配置します。`docs/first-run.md`、`Install-WhisperModel.ps1`、`Initialize-VoisonaDictionary.ps1`が配布先でも読める・実行できることを、`scripts/Test-SetupAssets.ps1`で確認します。補助スクリプトの既存ファイル保持・取得失敗時の動作は`scripts/Test-SetupHelpers.ps1`で検証します。

```powershell
./scripts/Test-SetupHelpers.ps1
./scripts/Test-SetupAssets.ps1
```

資料・補助スクリプトはv0.0.2以降のZIP/setupへ同梱します。公開済みv0.0.1のタグ・ZIP・setupを置き換えず、モデルの取得は利用者による補助実行時だけに行います。インストール直後の完全自動修復には、外部モデルを含む接続設定と同読み2票以上が必要で、`doctor.ready=true`と区別します。

公開は`gh repo create`／`git push`／`gh release create`を、リリース許可があるときだけ行います。配布物を別配置へ展開し、doctor・合成・文字起こし・CLI・管理IPCを確認してから公開します。リリース後はGitHubから再取得したZIPのハッシュを照合します。公開したZIPとsetupは認証なしで再取得して容量・ハッシュを照合します。

## CLIとGUIの辞書同期

CLIによる辞書更新後のGUIへの反映は、[CLI辞書更新後のGUI同期規定](cli-gui-dictionary-sync.md)を実装時の必須要件とします。

## 管理連携

WPFのDispatcherを使う管理契約2の実装を子内に保持します。SID別・CurrentUserOnlyのパイプ、操作期限、要求サイズ、expectedPid、同一セッションと実行パスの検査を備えます。変換中はstopを拒否し、自動起動予約は作成しません。

`--instance-id`と`--settings`を試験で指定し、通常利用のプロセス・設定と隔離します。`--smoke-report`は初期化後の実WPFツリーからタイトル・ボタン説明をJSONへ記録する試験用入口です。


## KotorinToys用インストーラー

scripts/Build-Release.ps1はtool.jsonの製品版を使い、新しいZIPとSHA256SUMS.txtを生成します。既存ZIPは上書きしません。別の仮想環境を使う場合は-PythonExecutableで指定します。

scripts/Build-Installer.ps1は、同じ版のZIPと明示したSHA-256、自己完結型の共通Maintenance、署名確認済みInno Setupコンパイラー、同じ採用ソースの.NET発行物を入力にします。backend・EXE・製品定義の版を照合し、標準Inno EXE・ReadingRepair-packages.json・ReadingRepair-SHA256SUMS.txtを新規出力へ生成します。

```powershell
$build=Get-Content ./release/v0.0.2/build-result.json -Raw | ConvertFrom-Json
./scripts/Build-Installer.ps1 -PortableArchive $build.archive -ExpectedArchiveSha256 $build.sha256 -MaintenanceDirectory <共通Maintenanceの自己完結出力> -Compiler <署名確認済みISCC.exe> -ApplicationDirectory $build.bundle -RegistrationDirectory (Join-Path $build.bundle registration)
```

共通Maintenanceと標準テンプレートの採用ソースはKotorinToysの公開mainです。installer/product.issは採用した標準テンプレートのコピーを保持します。導入時はKotorinToys本体のインストールを必要とせず、setupだけで現在ユーザーへ導入できます。配布入力の秘密検査・本体の公開台帳照合を行ってから公開します。既存v0.0.1のタグ・ZIP・setupは変更しません。
