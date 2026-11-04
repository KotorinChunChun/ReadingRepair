# 初回設定とCLI実行

配布版はPython実行環境、Whisperライブラリ、.NET実行環境を同梱しています。モデル本体、PowerShell 7、ログイン済みCodex CLI、使用するTTS本体・ボイス・認証情報は別途必要です。開発用Pythonや.NET SDKの導入は、ソースから開発する場合の[開発手順](development.md)を参照してください。

ここで追加した2本の補助スクリプトと資料は、次回のZIP/setupビルドから同梱します。公開済みv0.0.1の配布物は置き換えません。旧配布物で使う場合は、この版のソースから`Install-WhisperModel.ps1`と`Initialize-VoisonaDictionary.ps1`を展開先へコピーしてください。これらは単独で実行できます。

## 1. 起動場所と接続情報

PowerShell 7（`pwsh`）でインストール先またはZIP展開先へ移動します。以下は現在ユーザー用インストール先の例です。

```powershell
Set-Location (Join-Path $env:LOCALAPPDATA 'Programs/ReadingRepair')
codex login status
```

Codexが未認証なら、本人が`codex login`を完了してください。VoiSona Talkは起動・ログインし、少なくとも1つのボイスライブラリをダウンロードします。「編集 → 環境設定 → API」でAPI用パスワードを設定し、REST APIを有効にします。既定ポートは32766です。APIパスワードはVoiSonaのログイン用パスワードとは別に設定できます。[VoiSona公式手順](https://manual.voisona.com/ja/talk/pc/2b6e9bc7efb180ea86ccc6c7347e9ca6)

`tts.env.example`と`reviewers.env.example`をアプリの外へコピーします。既存ファイルを置き換えない例です。

```powershell
$connectionDirectory = Join-Path $env:LOCALAPPDATA 'ReadingRepair/connections'
New-Item -ItemType Directory -Path $connectionDirectory -Force | Out-Null
foreach ($name in @('tts', 'reviewers')) {
    $target = Join-Path $connectionDirectory ($name + '.env')
    if (-not (Test-Path -LiteralPath $target)) {
        Copy-Item -LiteralPath ($name + '.env.example') -Destination $target
    }
}
$ttsEnv = Join-Path $connectionDirectory 'tts.env'
```

外部ファイルの`VOISONA_USER`へAPI画面のユーザー名、`VOISONA_PASSWORD`へAPI用パスワードを本人が記入します。値をCLI引数・設定JSON・Git・共有ログへ貼らないでください。既存の.envを使う場合は、その絶対パスを`tts_env`へ指定できます。

## 2. 実際のボイス名と版を確認する

`ui_ja_JP`などの初期設定値は、ボイスがダウンロード済みであることを意味しません。公式APIの`voices`で確認します。次の例は.envの値をメモリー上で読み、ボイス一覧だけを表示します。

```powershell
$connection = @{}
foreach ($line in Get-Content -LiteralPath $ttsEnv) {
    if (-not $line.Trim() -or $line.TrimStart().StartsWith('#')) { continue }
    $pair = $line.Split('=', 2)
    if ($pair.Count -eq 2) { $connection[$pair[0].Trim()] = $pair[1].Trim().Trim('"', "'") }
}
$base = [Uri]$connection.VOISONA_BASE_URL
if ($base.Scheme -notin @('http', 'https') -or
    $base.Host -notin @('127.0.0.1', 'localhost', '[::1]', '::1') -or
    $base.UserInfo -or $base.Query -or $base.Fragment) { throw 'ループバックAPIのURLを指定してください。' }
$basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(
    $connection.VOISONA_USER + ':' + $connection.VOISONA_PASSWORD))
try {
    $voices = Invoke-RestMethod -Uri ($base.GetLeftPart('Authority') + '/api/talk/v1/voices') `
        -Headers @{Authorization = 'Basic ' + $basic} -MaximumRedirection 0
    $voices.items | Select-Object voice_name, voice_version, languages
}
finally { $connection.Clear(); $basic = $null }
```

HTTP 401ならユーザー名・APIパスワード、接続拒否ならアプリの起動・API有効化・ポートを確認します。`items`が空ならボイスのダウンロード完了をVoiSona側で確認します。Tanaka Sanの内部名は`tanaka-san_ja_JP`ですが、`voice_version`は実際の応答に合わせます。

## 3. Whisperモデルと新規辞書を用意する

```powershell
$modelPath = Join-Path $env:LOCALAPPDATA 'ReadingRepair/models/faster-whisper-small'
./Install-WhisperModel.ps1 -Destination $modelPath
$dictionaryPath = Join-Path $env:APPDATA 'Techno-Speech/VoiSona Talk/Talker/user_dict_ja_jp.dic'
./Initialize-VoisonaDictionary.ps1 -DictionaryPath $dictionaryPath
```

モデル取得補助は[公式のfaster-whisper small](https://huggingface.co/Systran/faster-whisper-small)のリビジョン`536b0662742c02347bc0e980a01041f333bce120`から4ファイル（約486 MB）を取得します。全ファイルのサイズとSHA-256が一致してから保存先を確定し、取得途中のデータを完成モデルとして配置しません。モデルはZIP/setupには同梱せず、利用者がこのコマンドを実行したときに取得します。

同じモデルが保存済みなら検証して再利用します。指定先に異なる内容や不完全なモデルがある場合は上書きせず止まるため、別の新規フォルダーを指定してください。既存のfaster-whisper形式モデルがある場合は取得せず、そのフォルダーを設定へ指定できます。

辞書補助は未作成のパスだけに0バイトの空UTF-8辞書を作ります。最初の単語を手入力する必要はありません。既存辞書が空でも語句を含んでいても、内容を変更しません。語句の追加は後のReadingRepair登録ヘルパーが行います。VoiSonaが別の辞書を使っている環境では、その実際のパスへ合わせてください。

## 4. 設定を保存して依存を診断する

通常設定・履歴から分けて確認する例です。`-SettingsFile`だけでは履歴は分離されないため、`runs_root`も指定します。設定JSONに認証値は含めません。

```powershell
$workRoot = Join-Path $env:LOCALAPPDATA 'ReadingRepair/first-run'
New-Item -ItemType Directory -Path $workRoot -Force | Out-Null
$settingsFile = Join-Path $workRoot 'settings.json'
$patchFile = Join-Path $workRoot 'settings-patch.json'
$voiceName = 'tanaka-san_ja_JP' # 使用するボイスのvoice_nameへ変更
$voice = @($voices.items | Where-Object voice_name -eq $voiceName)[0]
if (-not $voice) { throw 'APIの一覧から使用するボイスを選んでください。' }
@{
    tts_engine = 'voisona'
    tts_env = $ttsEnv
    reviewer_env = (Join-Path $connectionDirectory 'reviewers.env')
    whisper_model = $modelPath
    dictionary_file = $dictionaryPath
    voice = $voice.voice_name
    voice_version = $voice.voice_version
    runs_root = (Join-Path $workRoot 'runs')
} | ConvertTo-Json | Set-Content -LiteralPath $patchFile -Encoding utf8
./Invoke-ReadingRepair.ps1 save-settings -SettingsFile $settingsFile -RequestFile $patchFile
./Invoke-ReadingRepair.ps1 doctor -SettingsFile $settingsFile
```

GUIの通常設定へ反映する場合は設定画面で同じ保存先・ボイスを指定するか、内容を確認したうえで`save-settings`の`-SettingsFile`を省略して通常設定へ保存します。以後のCLIには、対象の設定ファイルを一貫して渡します。

`ready=true`は基本依存の準備完了です。Gemini・Sarashinaの`warning`や`not_configured`は独立照会が未設定であることを示し、無人の多数決が利用できる状態とは限りません。完全な自動採用には、一次LLMを含め同じ読みが有効2票以上必要です。接続方式・モデル名・キーは`reviewers.env.example`と設定画面に合わせて指定します。

## 5. 合成だけの確認と、自動修復の実行

`synthesize`は辞書修復やWhisper比較を行いません。まず接続だけ試す場合は、新しい出力名を指定します。

```powershell
$preview = Join-Path $workRoot ('preview-' + [guid]::NewGuid().ToString('N') + '.wav')
./Invoke-ReadingRepair.ps1 synthesize -SettingsFile $settingsFile -TextFile ./sample.txt -OutputFile $preview
./Invoke-ReadingRepair.ps1 transcribe -SettingsFile $settingsFile -AudioFile $preview
```

原文を保持して辞書登録・再生成まで行うのは`repair`ジョブです。

```powershell
$created = (& ./Invoke-ReadingRepair.ps1 create -SettingsFile $settingsFile -TextFile ./sample.txt -Mode repair | ConvertFrom-Json).result
$job = $created.id
./Invoke-ReadingRepair.ps1 execute -SettingsFile $settingsFile -Job $job
./Invoke-ReadingRepair.ps1 status -SettingsFile $settingsFile -Job $job
```

`completed`なら登録後音声を再生できます。`pending_confirmation`は完了ではありません。

```powershell
./Invoke-ReadingRepair.ps1 audio -SettingsFile $settingsFile -Job $job -Phase after -Play
```

## 確認待ちと指定読み

確認待ちは、ジョブの`answers-template.json`を元に本人が採用・不採用、読み、理由を回答し、`answer -RequestFile`の後に同じジョブを`execute`して反映します。`registration.surface`と`registration.reading`で文脈を含む語句全体を登録できます。例えば舞台用語の「上手」は、単独語を一律登録するより「舞台の上手側」のように範囲を限定します。

本人が最初から正しい読みを明示できる場合は、`create -RequestFile`に次のような要求JSONを渡せます。これは手順説明用の架空例です。

```json
{
  "text": "舞台の上手側から、照明係が合図します。",
  "mode": "repair",
  "known_readings": [
    {"surface": "舞台の上手側", "reading": "ブタイノカミテガワ"}
  ]
}
```

指定読みは本人が明示した基準であり、独立モデルの一致票ではありません。AIが作った推測を本人の回答へ流用したり、未設定の外部モデルを同意票として記録したりしないでください。指定読みも原文の漢字を置換する入口ではなく、ReadingRepairが原文と辞書を照合するための入力です。

## 失敗後の確認と再開

```powershell
./Invoke-ReadingRepair.ps1 status -SettingsFile $settingsFile -Job $job
./Invoke-ReadingRepair.ps1 log -SettingsFile $settingsFile -Job $job
./Invoke-ReadingRepair.ps1 llm-log -SettingsFile $settingsFile -Job $job
./Invoke-ReadingRepair.ps1 execute -SettingsFile $settingsFile -Job $job
```

`execute`は完了済みの工程を再利用します。途中失敗したからといって履歴や音声、登録済み語句を削除する必要はありません。ジョブは作成時の設定を保持するため、通常設定を変更しても既存ジョブの接続先は変わりません。接続先・モデル・保存先を変える試験は新しいジョブで行います。

| 状態・工程 | 確認と対応 |
| --- | --- |
| Whisperモデルの`error` | ライブラリではなく、設定のフォルダーに`model.bin`などのモデル実体があるか確認する。 |
| 辞書の`FileNotFoundError` | `dictionary_file`が実際のネイティブ辞書か確認し、未作成の場合だけ辞書補助で新規作成する。 |
| `pending_confirmation` | 外部モデルの未設定・失敗・判断不能を確認する。本人の回答を反映するか、接続を設定して`-RetryReviewers`で再照会する。 |
| 「誤読候補の根拠が不正」「LLM基準読みが…一致しない」 | LLM結果の形式・一致検証で停止した状態。同じジョブを再開して再照会できる。繰り返す場合は送受信記録を確認し、結果ファイルを成功に書き換えない。 |
| 文脈付き語句と短語の基準が重複して停止 | 本人が読みを確定した場合は、語句全体の`known_readings`を指定した新しいジョブを作れる。旧ジョブの失敗記録は保持し、無確認で指定読みを捏造しない。 |
| 「入力欄へのメッセージ反映を確認できません」 | VoiSonaの起動、辞書パネル、入力可能な対話セッションを確認する。登録済み語句を保持したまま同じジョブを再開し、残りを照合する。 |
| `dictionary_conflict` | 既存の読みと候補を見直す。検証や競合判定を無効化して上書きしない。 |
| 合成先が既に存在 | 単独`synthesize`には新しい出力名を使う。ジョブの再開では完了済みの音声工程だけを再利用する。未完了の合成で部分WAVが残り既存エラーになる場合は、旧記録を保持して新しいジョブで再試行する。 |

登録は同梱`registration/ReadingRepair.Registration.exe`がUIAと`SendMessageTimeout`で行います。通常の背面ウィンドウへ対象HWNDのメッセージを送り、最小化時は復元します。実マウス・キーボードは使いません。ウィンドウや入力欄が取得できない場合には止まります。配布版にはヘルパー実行環境も同梱するため、通常利用で自前のUI自動操作スクリプトを作る必要はありません。

最終確認ではアプリの状態、辞書の読戻し、登録後の発音解析、Whisper比較、実際の試聴を分けて確認します。Whisperの同音語・漢字への逆変換やLLMの評価値だけでは、すべての読みの正しさを保証できません。共有するレポート・ログには原文・辞書・LLM応答が含まれるため、公開前に内容を確認してください。
