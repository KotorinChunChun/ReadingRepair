# ReadingRepair v0.0.1

VoiSonaTalkAIの読み検証・辞書改善機能を、ReadingRepairとして独立させたWindowsアプリです。

- VoiSona Talkと、JSONをPOSTしてWAVを返すHTTP音声APIに対応。
- 辞書全件を添付した複数LLM比較、同読み2票の仮採用、個別確認、競合確認、辞書登録と音声再生成。
- Whisperの文字起こしと前後評価、試聴、工程別HTML、LLM送受信ログ。
- Python/.NET実行環境を同梱。旧VoisonaTalkAIのソース・venvは不要。
- CLIとWindows画面で処理・設定・履歴を共有。KotorinToysの管理契約2に対応。

ZIPを展開してReadingRepair/ReadingRepair.exeを起動してください。PowerShell 7、ログイン済みCodex CLI、Whisperモデル、使用するTTSと認証設定は別途必要です。APIキー、利用者設定、モデル、検証履歴、生成音声は同梱していません。

123件の回帰、UIA登録ヘルパー5件、自己完結ZIPの別配置で実音声生成・Whisper・実LLMの一巡と管理IPCを確認済みです。他社の実HTTP TTSへの接続と人間の聴取は未実施であり、HTTPアダプターはローカル検証サーバーで確認しました。

このリリースは非公開リポジトリ内の配布です。取得にはアクセス権のあるGitHubアカウントが必要です。SHA-256は同梱のSHA256SUMS.txtを参照してください。
