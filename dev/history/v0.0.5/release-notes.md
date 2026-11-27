同梱SQLiteを3.54.1に更新しました。文字起こし先にTranscriptionServerを指定でき、VoiSona Talk APIのローカル中継と、読み補正を実行しない音声合成をCLIから利用できます。

[アプリの概要・使い方（README）](https://github.com/KotorinChunChun/ReadingRepair/blob/v0.0.5/README.md)

## ダウンロード

Windows 11 x64対応です。.NETとPythonを同梱しています。音声化にはTTS、文字起こしにはローカルWhisperモデルまたはTranscriptionServer、LLM判定にはCodex CLIなどの外部設定が必要です。

- `ReadingRepair-0.0.5-setup.exe` — 新規インストール・更新用
- `ReadingRepair-v0.0.5-win-x64.zip` — 展開して使うポータブル版
- `ReadingRepair-SHA256SUMS.txt`、`SHA256SUMS.txt` — それぞれセットアップとZIPのSHA-256照合用

Windows用セットアップは未署名です。[Microsoft Edgeでのダウンロード手順](https://github.com/KotorinChunChun/KotorinToys/blob/main/docs/github-release-download-edge.md)

## インストール・更新

- 初めて使う場合はセットアップを実行するか、ZIPを展開して `ReadingRepair.exe` を起動します。
- 更新前に処理を終了してReadingRepairを閉じます。既存の設定・履歴はLocalAppDataのデータを引き続き使用します。
- KotorinToysでは「状態を更新」してからReadingRepairを選び、「インストール」または「更新」を実行します。

## 確認範囲

- VoiSona Talk APIの中継を通じて音声を合成し、TranscriptionServer v0.1.21とローカルWhisperで文字起こしを確認しました。
- 既存設定ではローカルWhisperを使用します。中継はCLIで明示的に起動した場合に利用できます。

## 主な変更

- 同梱SQLiteを3.54.1に更新しました。
- 文字起こし方式にTranscriptionServerを追加しました。
- `serve-voisona` と `synthesize-voisona` を追加しました。

[使い方](https://github.com/KotorinChunChun/ReadingRepair/blob/v0.0.5/docs/guide.md) · [不具合を報告](https://github.com/KotorinChunChun/ReadingRepair/issues)
