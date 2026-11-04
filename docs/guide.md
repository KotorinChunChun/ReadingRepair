# ReadingRepair の使い方

## KotorinToysから導入

KotorinToysで「状態を更新」し、ReadingRepairを選んで「インストール」を実行します。公開版・容量・SHA-256の確認後、現在ユーザーのPrograms/ReadingRepairへ導入します。自動起動は有効にしません。Pythonと.NETの実行環境を同梱し、既存の設定・履歴はLocalAppData/ReadingRepairへ保持します。

GitHub ReleasesからReadingRepair-0.0.1-setup.exeを直接取得することもできます。ZIP版もログイン不要で利用できます。TTS・Whisperモデル・Codex CLIの初期設定は導入方式に関係なく必要です。

## 準備

Windows 11 x64を対象とします。配布ZIPは任意のフォルダーへ展開して使えます。旧VoisonaTalkAIやKotorinToys本体のソースは不要です。

初回は[モデル取得・接続・辞書作成を含む手順](first-run.md)を参照してください。配布版を使う場合、Pythonや.NET SDKの別インストールは不要です。Whisperライブラリとモデル本体は別で、モデルは外部に配置します。

1. PowerShell 7とCodex CLIを用意し、`codex login`で一次LLMを使用可能にします。
2. faster-whisper形式のモデルを準備して「設定」のWhisperモデルに指定します。モデルは配布しません。
3. `tts.env.example`と`reviewers.env.example`をソース外へコピーし、キーを設定します。既定先は`C:/AI/env/ReadingRepair/tts.env`と`reviewers.env`です。
4. 「設定」でTTSエンジン、ボイス、接続ファイル、外部モデル、辞書を指定して保存します。「依存を診断」で接続を確認します。

VoiSona Talkは起動済みのローカルREST APIを使用します。ネイティブ辞書への新規登録だけはVoiSonaの画面をUIA/SendMessageで操作します。既存辞書を書き換えるために直接ファイル編集することはありません。

初回でネイティブ辞書がない場合は`Initialize-VoisonaDictionary.ps1`で空の辞書を新規作成できます。既存ファイルは保持します。登録ヘルパーは通常表示の背面ウィンドウへメッセージを送り、最小化中なら復元します。実マウス・キーボードでの入力は使いません。

HTTP TTSは[エンジン接続](tts-engines.md)を参照してください。API固有の設定は利用者が指定します。

## 変換と確認

「変換の開始」は原文を保存し、辞書全件を添付した一次LLMの読み仮説、WAV生成、Whisper文字起こし、差分比較を行います。一次LLM・Gemini・Sarashinaの有効な同読み2票以上を仮採用し、採用候補を辞書と照合して登録・再生成します。照会失敗と判断不能は棄権です。

`doctor`の`ready=true`だけでは独立した2票が揃うとは限りません。外部モデルが未設定なら、TTSとの差がある候補は確認待ちになります。実際の本人回答と指定読みを記録し、AIの推測を本人の回答や独立モデルの票として扱わないでください。

確認待ちの語は各行の「採用」「不採用」で保存できます。文脈を限定したいときは「舞台の上手」のような語句と全体の読みを指定します。全候補の回答後、「回答を反映して再開」で登録・再生成へ進みます。不採用は登録しない判断であり、元の読みが正しいことの確定とは区別します。

「検証のみ」は辞書への追加前に停止します。「候補を適用して再開」で追加・再生成できます。競合がある場合は既存辞書を上書きせず止まります。

「テスト再生」は選択した履歴の登録後音声を優先して再生します。履歴から登録前後の音声を個別に再生できます。進行ログとHTMLには工程の入力、文字起こし、問題、採用根拠、登録結果、評価を保存します。「LLM送受信」ではモデルごとの実プロンプトと応答を確認できます。共有するときは原文・辞書・応答が含まれることを確認してください。

## 辞書

「ユーザー辞書」は現在選択したエンジンの登録状態を表示します。追加は表記・読みを入力し「重複・競合を確認」から「確認した候補を追加」の順です。この手動追加だけでは原文を再生成しません。

VoiSonaは既存ネイティブ辞書を使います。HTTP TTSは専用JSON辞書を使い、長い語句を優先して音声化直前に置換します。プロファイルとAPI用辞書パスを分けてサービスごとの読みを管理できます。アクセント・音程の制御には対応しません。

## CLI

pwshで展開先（開発時はリポジトリ）へ移動して実行します。設定ファイルを分離すると試験と通常利用を混在させずに済みます。

```powershell
./Invoke-ReadingRepair.ps1 doctor
./Invoke-ReadingRepair.ps1 engines
./Invoke-ReadingRepair.ps1 create -TextFile ./sample.txt
./Invoke-ReadingRepair.ps1 execute -Job <実行ID>
./Invoke-ReadingRepair.ps1 status -Job <実行ID>
./Invoke-ReadingRepair.ps1 log -Job <実行ID>
./Invoke-ReadingRepair.ps1 llm-log -Job <実行ID>
./Invoke-ReadingRepair.ps1 answer -Job <実行ID> -RequestFile ./answers.json
./Invoke-ReadingRepair.ps1 execute -Job <実行ID> -RetryReviewers
./Invoke-ReadingRepair.ps1 audio -Job <実行ID> -Phase after -Play
./Invoke-ReadingRepair.ps1 dictionary
./Invoke-ReadingRepair.ps1 check-dictionary -RequestFile ./candidates.json
./Invoke-ReadingRepair.ps1 add-dictionary -RequestFile ./checked-candidates.json
./Invoke-ReadingRepair.ps1 synthesize -TextFile ./sample.txt -OutputFile ./preview.wav -Play
./Invoke-ReadingRepair.ps1 transcribe -AudioFile ./preview.wav
```

APIキーはCLI引数・JSON要求へ入れません。設定変更は`save-settings -RequestFile`、読み回答はジョブの`answers-template.json`の形式を使います。手動追加には`check-dictionary`が返す`dictionary_sha256`と候補`entries`を渡します。

独立した設定で試すときは、すべてのコマンドへ同じ`-SettingsFile`を渡し、`runs_root`も試験用へ分離します。`synthesize`は音声を作るだけで、自動修復を行いません。自動修復は`create -Mode repair`と`execute`を使用します。部分登録やLLM結果の形式検証で止まった場合の[確認・再開手順](first-run.md#失敗後の確認と再開)も参照してください。

`backend/ReadingRepair.Backend.exe`は同じコマンドを直接受け付け、JSON Linesで進行と結果を返します。`--settings <ファイル>`、`--workspace <展開先>`、`--request <JSON>`を指定できます。GUIはこのCLIと同じ処理を呼びます。

## 保存と終了

通常データは`%LOCALAPPDATA%/ReadingRepair`です。履歴の保存先は設定可能です。変換中は停止ボタンで安全な区切りまで待ってから閉じます。自動起動予約は作成しません。

KotorinToysの管理契約2に対応し、通常起動は画面を表示、`--startup`または`--hidden`は無表示です。ユーザーSID別パイプでstatus/show/stopを受け付け、変換中のstopは拒否します。
