ReadingRepair v0.0.2を公開します。

- PR #1の初回設定ガイドを同梱。TTS接続、Whisperモデル、辞書、確認待ちと再開の手順を整理しました。
- Install-WhisperModel.ps1を同梱。固定revisionのモデルをサイズ・SHA-256で検証し、全件成功後に配置します。既存モデルを上書きしません。
- Initialize-VoisonaDictionary.ps1を同梱。未作成の場合だけ新しい空辞書を作成し、登録済み辞書を保持します。
- ZIP／setup／CLI／アプリの版を0.0.2へ統一しました。Pythonと.NET 10.0.14を同梱しています。
- KotorinToysから新規導入・v0.0.1からの更新が可能です。状態を更新して公開版を確認してください。

通常はReadingRepair-0.0.2-setup.exeを使用してください。ZIP版はReadingRepair-v0.0.2-win-x64.zipを展開してReadingRepair.exeから起動できます。

Whisperモデル本体、ログイン済みCodex CLI、PowerShell 7、TTSの接続設定は別途必要です。モデル取得は同梱スクリプトを実行したときに行います。既存v0.0.1のタグ・ZIP・setupは変更していません。

検証: Python123件、準備・同梱17件、登録ヘルパー5件、配布CLIの辞書反映・再生成、Whisper実モデル読込み、管理IPC、setup全1,860ファイルのSHA-256、秘密情報検出0件を確認しました。自動読み判定や実音声の正解を保証するものではありません。
