# VoiSona TalkのAPIをReadingRepair経由で使う

既存アプリが使う `http://127.0.0.1:32766/api/talk/v1/` をReadingRepairが受け付け、同じPCのVoiSona Talkへ転送します。`localhost` と、IPv6が有効なPCでは `[::1]` も使えます。合成・解析・ジョブ照会・削除の要求を既存APIの形式で転送します。認証はVoiSona Talkが行い、認証情報や原文は中継のログへ保存しません。中継でReadingRepairの読み補正や辞書登録は実行せず、VoiSona Talk自身の辞書は通常どおり使われます。

1. VoiSona Talkを使う処理を終了します。VoiSona Talkの「編集 → 環境設定 → API」でREST APIを一時的に無効にし、待ち受けポートを `32767` に変更してから再度有効にします。パスワードは既存のものを使います。詳細は [公式のREST APIチュートリアル](https://manual.voisona.com/ja/talk/pc/2b6e9bc7efb180ea86ccc6c7347e9ca6) を参照してください。
2. ReadingRepairのフォルダーで下記を実行し、`type: ready` を確認します。クライアントは従来の `32766` を使います。中継の起動中はこのプロセスが待受を維持します。

```powershell
pwsh -NoProfile -File ./Invoke-ReadingRepair.ps1 serve-voisona
```

VoiSona Talkも起動しておいてください。`GET /api/talk/v1/readingrepair-health` は中継の待ち受けだけを確認します。本体も確認するときは、従来の認証で `GET /api/talk/v1/voices` を呼び出してください。本体が停止中の要求にはHTTP 502を返します。

停止は前面で起動したコンソールの Ctrl+C で行います。スタートアップへ登録した環境で元の構成に戻すときは、中継を止め、スタートアップの中継ショートカットを外してからVoiSona Talkの待ち受けを `32766` へ戻してください。本体の設定を変えず試すには `-ListenPort 32767 -UpstreamPort 32766` を指定し、テストするクライアントだけを `32767` へ向けます。

## 読み補正なしでWAVを作る

```powershell
pwsh -NoProfile -File ./Invoke-ReadingRepair.ps1 synthesize-voisona -TextFile ./input.txt -OutputFile ./speech.wav
```

VoiSona Talkへ原文を渡し、WAVを作ります。Whisper、LLM、読み解析、ReadingRepairの辞書登録や履歴作成は呼びません。既存の `synthesize` は合成と読み解析を行うため、従来の呼び出しに変更はありません。
