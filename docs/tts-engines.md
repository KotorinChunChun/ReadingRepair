# TTSエンジン

`backend/tts_backends.py`の`create(settings)`がTTSの選択境界です。合成・発音解析・辞書登録の能力差を持ち、読み判定のパイプラインは共通です。

| エンジン | 音声 | 発音解析 | 辞書反映 |
| --- | --- | --- | --- |
| voisona | ローカルREST | TSML | VoiSonaのネイティブ辞書、UIAとSendMessage |
| http-wav | JSONをPOSTしPCM WAVを受信 | 非対応を記録 | ReadingRepair専用JSON辞書で原文を置換 |

## VoiSona Talk

`tts_env`に指定した外部ファイルで`VOISONA_BASE_URL`、`VOISONA_USER`、`VOISONA_PASSWORD`を設定します。URLはループバック専用です。ボイス名とバージョンはアプリ設定で指定します。`dictionary_file`にはVoiSonaの既存辞書を指定します。

接続先の既定ポートは32766です。HTTP 401は認証未完了、`voices.items=[]`はAPIから利用できるボイスがない状態なので、VoiSona側のライブラリ取得を確認します。既定の設定値はインストール済みボイスを示しません。実際の`GET /api/talk/v1/voices`に含まれる`voice_name`と`voice_version`を使います。[初回設定](first-run.md)に秘密を表示しない確認例があります。

辞書がない場合は`Initialize-VoisonaDictionary.ps1`で未作成のファイルだけを空のUTF-8辞書として作れます。語句の追加は同梱`ReadingRepair.Registration.exe`によるUIAと`SendMessageTimeout`を使い、直接追記はしません。最小化は復元しますが、アプリ未起動・対話セッション外・入力欄が取得できない状態では登録できません。途中まで登録できた語句は保持し、同じジョブの再開で残りを照合します。

## HTTP WAV API

設定を`tts_engine=http-wav`にし、`tts_env`へ外部接続設定を指定します。`api_dictionary_file`は専用JSONファイルです。VoiSona辞書とは分離されます。`tts_profile`の変更だけをCLIで保存するとプロファイル別の既定辞書へ切り替わります。GUIで変更する場合はAPI用JSON辞書パスも指定してください。

```dotenv
TTS_URL=https://your-tts-service.example/v1/audio/speech
TTS_API_KEY=
TTS_BODY_JSON={"model":"your-model","input":"{text}","voice":"{voice}","response_format":"wav"}
```

上記は接続形式の例であり、特定サービスとの接続済み設定ではありません。サービスの正式仕様に合わせてJSONのキー・model・voiceを指定してください。`{text}`は辞書適用後の文章、`{voice}`と`{voice_version}`はアプリの値へ置換します。JSON中の文字列値で使用できます。

Bearer認証を使用し、`TTS_API_KEY`が空なら認証ヘッダーを付けません。HTTPSまたはループバックHTTP、クエリ・認証値のないURLに限定し、リダイレクトを拒否します。POSTへの応答は64MiB以内の非圧縮WAVが必要です。MP3、JSON内のbase64、非同期ジョブAPI、独自署名認証には専用アダプターを追加してください。

音声化へ送った置換後本文と辞書ハッシュは各WAVの`.tts-input.json`へ記録し、通常の一巡履歴HTMLにも含めます。HTTPの認証ヘッダー・エラー本文は記録しません。発音解析がないことはWhisper未実施という意味ではありません。

## アダプター追加

`id`と`capabilities`に加え、次のメソッドを実装して`ENGINES`と`create`へ登録します。

- `preflight()`：接続・ボイスと能力を公開形式で返す。秘密は返さない。
- `synthesize(text, output)`：非圧縮WAVを生成する。原文の順序を保ち、辞書方式を適用する。
- `analyze(text)`：TSMLなら`analyzed_text`を返す。非対応なら`supported=false`と理由を返す。期待する読みを実測値へ流用しない。
- `register(run_dir, text, entries)`：直前の重複・競合検査、登録と読戻し、方法と各候補の状態を返す。

辞書スナップショットは共通テーブル（優先順位・表記・読み・アクセント核）へ変換し、全LLMへ添付します。既存辞書のネイティブ形式とReadingRepair JSON形式は区別します。新アダプターには登録前後・競合・失敗時の秘密非表示・再開条件の試験を追加してください。
