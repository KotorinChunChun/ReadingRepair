# VoiSona 読み自己修復

VoiSona合成、Whisper文字起こし、LLMの読み比較、UIAによる辞書登録、登録後の再評価を行う独立Windowsアプリと共通CLIです。

```powershell
pwsh -File .\tools\PronunciationDictionaryLab\Start-ReadingRepair.ps1
```

CLIでビルド・診断する場合は`pwsh -File .\tools\PronunciationDictionaryLab\Invoke-ReadingRepair.ps1 doctor -Build`を使います。GUIを起動せずに実行できます。

画面から原文・指定読み・開始・停止・確認待ちへの回答・履歴・音声を操作できます。CLIは`application.py`の`doctor/create/execute/status/history/answer/stop/audio/export`です。既存の`Start-Lab.ps1`も継続利用できます。

「ユーザー辞書」では現在の登録内容を取得し、表記と読みの追加前に重複・競合を確認できます。CLIは`dictionary/check-dictionary/add-dictionary`です。改行・空行を含む原文も処理でき、旧保存不具合で開始できなかった原文は、元のハッシュから内容を確認できる場合に再開できます。

各ボタンに動作説明を付け、候補の各行は採用・不採用を1クリックで保存できます。判断は同じ読みの有効票2票以上を多数決で仮採用します。「LLM送受信」でモデル名とプロンプト・応答を読み、詳細経緯は`log`、送受信は`llm-log`でも取得できます。

利用方法と評価の限界は[利用手順](../../docs/pronunciation-dictionary-lab.md)、版別の実験結果は[v0.4.0実装報告](../../dev/history/v0.4.0/v0.4.0-imp.md)を参照してください。
