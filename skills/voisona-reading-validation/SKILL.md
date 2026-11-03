---
name: voisona-reading-validation
description: ReadingRepairのCLIでTTS音声とWhisper・複数LLMの読みを比較し、辞書反映・前後評価を履歴へ残す。
---

# ReadingRepairによる読み検証

ユーザーが指定したReadingRepair、または`C:/develop/KotorinToys/tools/ReadingRepair`でAGENTS.md、docs/guide.md、docs/tts-engines.mdを読む。旧VoisonaTalkAIの実装をコピーせず、Invoke-ReadingRepair.ps1を使う。

`doctor`、`engines`、`dictionary`で現在の接続・能力・全件辞書を確認する。原文の`create`から`execute`へ進み、LLMの比較と辞書全件テーブルの送信を共通処理へ任せる。通常工程はCLIで行い、画面操作は表示確認やVoiSonaネイティブ辞書ヘルパーの診断だけに限定する。

一次案とGemini・Sarashinaの有効な同読み2票を仮採用する。失敗・判断不能は棄権、2票未満はpending_confirmationで停止する。`status`、`log`、`llm-log`で理由を確認し、実際の利用者回答のみを`answer`へ保存して`execute`で再開する。保留のまま完了したと報告せず、架空の回答で実辞書へ登録しない。

文脈で読みが変わる場合は対象語と登録語句を分け、「舞台の上手」のようなまとまりを登録する。ユーザーの訂正は最新のものを使う。却下は登録しない判断であり、TTS側の正しさの確定とは扱わない。

外部設定は`C:/AI/env/ReadingRepair/`などソース外に置き、キーをプロンプト・ログ・成果物へ出さない。既に許可された送信や登録を再確認しない。TTSの発音解析非対応とWhisper未実施を区別する。

VoiSonaは専用UIA/SendMessageヘルパーを使い、辞書を直接編集しない。HTTP TTSはアプリ管理のJSON辞書を使う。最新辞書と重複・競合確認して新規のみ反映し、再生成・文字起こし・同基準評価を確認する。自動追加を繰り返さず、未解決なら根拠と共に保留する。

音声は`audio -Job <ID> -Phase after -Play`、HTMLは`export`を使う。実API接続、音声生成、再生、人間の聴取を別の証拠として報告する。実験データを公開リリースへ含めない。
