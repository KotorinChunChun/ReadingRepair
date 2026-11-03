# 開発・検証・配布

## 開発起動

Python 3.12、.NET 10 SDK、PowerShell 7を使用します。旧VoisonaTalkAIやKotorinToys親のソースはビルド依存ではありません。

```powershell
cd C:\develop\KotorinToys\tools\ReadingRepair
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-build.txt
./Start-ReadingRepair.ps1
```

## 検証

```powershell
$env:PYTHONUTF8='1'
./.venv/Scripts/python.exe -m unittest discover -s backend -p 'test_*.py' -q
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

公開は`gh repo create`／`git push`／`gh release create`を、リリース許可があるときだけ行います。配布物を別配置へ展開し、doctor・合成・文字起こし・CLI・管理IPCを確認してから公開します。公開後はGitHubから再取得したZIPのハッシュを照合します。

## 管理連携

WPFのDispatcherを使う管理契約2の実装を子内に保持します。SID別・CurrentUserOnlyのパイプ、操作期限、要求サイズ、expectedPid、同一セッションと実行パスの検査を備えます。変換中はstopを拒否し、自動起動予約は作成しません。

`--instance-id`と`--settings`を試験で指定し、通常利用のプロセス・設定と隔離します。`--smoke-report`は初期化後の実WPFツリーからタイトル・ボタン説明をJSONへ記録する試験用入口です。
