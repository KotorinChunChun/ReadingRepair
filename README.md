# ReadingRepair

日本語TTSの読みを検証し、ユーザー辞書と音声を改善するWindowsアプリです。VoiSona Talkと、JSONを受け取りWAVを返すHTTP音声APIに対応します。

[最新版をダウンロード](https://github.com/KotorinChunChun/ReadingRepair/releases/latest)して、インストーラーを実行するかZIPを展開して`ReadingRepair.exe`を起動します。Pythonと.NETの実行環境を同梱しています。GitHubへのログインなしでダウンロードできます。KotorinToysの一覧からも導入できます。初期設定にはPowerShell 7、ログイン済みCodex CLI、ローカルWhisperモデル、使用するTTSの設定が必要です。

**初めて使う場合は[初回設定とCLI実行](docs/first-run.md)から進めてください。** Whisperのライブラリは同梱していますが、モデル本体は別途取得が必要です。ボイスの名前・版、接続用.env、辞書の保存先も確認します。v0.0.2以降には、モデル取得用`Install-WhisperModel.ps1`と新規空辞書用`Initialize-VoisonaDictionary.ps1`を同梱しています。既存モデル・辞書は上書きしません。

原文を入力して「変換の開始」を押すと、音声生成、Whisper文字起こし、複数モデルの読み比較、辞書登録、音声再生成、前後評価まで進みます。判断が分かれた語は確認待ちになり、各行から採用・不採用を選べます。完了後は「テスト再生」で音声を確認できます。

設定・履歴は`%LOCALAPPDATA%/ReadingRepair`へ保存します。認証情報はソース外の`.env`で指定します。原文と登録済み辞書は読み判定のため設定したLLMへ送信されます。自動評価は人間の聴取による正解保証ではありません。

- [使い方・CLI](docs/guide.md)
- [初回設定・モデル取得・失敗後の再開](docs/first-run.md)
- [TTS APIの接続・拡張](docs/tts-engines.md)
- [開発・ビルド・検証](docs/development.md)
- [ライセンス](LICENSE)
