# VoiSona辞書のGit自動同期

VoiSona Talkで辞書を更新する一連の処理を終えると、独立した辞書リポジトリへ自動で取り込み、変更がある場合だけコミットできます。GUIとCLIは同じ終了処理を使います。自動Pushは行いません。

## 連携設定

通常設定ファイルと同じフォルダーに `dictionary-git.json` を置いて有効化します。通常利用では `%LOCALAPPDATA%/ReadingRepair/dictionary-git.json` です。`--settings` で設定を分離する場合は、その設定ファイルと同じフォルダーへ置きます。

```powershell
$configuration = @{
    format = 'readingrepair.dictionary-git.v1'
    enabled = $true
    repository = 'C:\develop\VoiSonaTalkDictionary'
    source_dictionary = (Join-Path $env:APPDATA 'Techno-Speech\VoiSona Talk\Talker\user_dict_ja_jp.dic')
}
$configuration | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $env:LOCALAPPDATA 'ReadingRepair\dictionary-git.json') -Encoding utf8
```

リポジトリにはGit管理領域と `scripts/Sync-Dictionary.ps1` が必要です。PowerShell 7とGitを使用します。連携ファイルには資格情報・原文・音声を保存しません。

許可した `source_dictionary` と実行対象の辞書パスが一致する場合だけ同期します。別プロファイルの辞書やHTTP TTSのJSON辞書は対象にしません。ファイルがない場合、または `enabled=false` の場合は無効です。読みモデルなど従来の設定値は変わりません。

## 同期するタイミング

`execute` と `add-dictionary` の最後に、辞書の排他ロックを保持したまま一度呼び出します。正常完了・確認待ち・中止・部分登録後の失敗でも、実ファイルに残った登録内容を取り込みます。語ごとのコミットは行いません。変更がなければ空コミットを作りません。

辞書同期CLIも同時実行を排他します。辞書以外のステージ済み変更がある場合は、別の作業を混ぜず停止します。コミット対象は辞書とmanifestだけで、メッセージに原文やAPIキーを入れません。

## 結果の確認と再試行

実行フォルダーの `dictionary-git-sync.json` と進行ログへ、同期結果・SHA-256・件数・コミットIDを保存します。読み検証ジョブのstatusにも `dictionary_git_sync` が付き、HTMLの進行記録から経緯を確認できます。

Git同期に失敗しても、登録済みの実辞書や変換結果は巻き戻しません。変換結果のstatusとGit同期のstatusは別に確認してください。Git側の問題を解消した後、次で実辞書の同期だけを再実行できます。

```powershell
./Invoke-ReadingRepair.ps1 sync-dictionary-git
```

完了済みジョブの `execute` を再実行した場合も、TTSを再生成せずGit同期を再試行します。通常の `dictionary`、`status`、`doctor`、`audio` の参照操作ではコミットしません。
