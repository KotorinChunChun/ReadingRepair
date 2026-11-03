using System.Windows;
using System.Windows.Controls;
namespace ReadingRepair.Desktop;
public partial class App : Application
{
    static readonly Dictionary<string,string> Explanations=new()
    {
        ["依存を診断"]="VoiSona接続、辞書、Python、Whisper、一次LLM、外部モデルのキー設定を確認します。音声生成や辞書登録は行いません。",
        ["変換の開始"]="原文を音声化し、WhisperとLLMで読みを確認します。採用が確定した候補は辞書へ登録して音声を再生成し、前後を評価します。判断が未確定の語は確認待ちで止まります。",
        ["検証のみ"]="原文の音声生成、文字起こし、読みの比較、候補作成まで行います。辞書への追加と登録後の再生成は行いません。適用する場合は「候補を適用して再開」を使います。",
        ["原文を開く"]="文章ファイルを選び、原文欄へ読み込みます。この操作だけでは変換しません。",
        ["テスト再生"]="選択した実行の生成済み音声を再生します。登録後の音声を優先し、登録後がなければ登録前を使用します。音声の生成後、処理が停止しているときに使えます。",
        ["再生を停止"]="現在の音声の試聴を止めます。変換処理や保存済み音声は変更しません。",
        ["選択した実行を再開"]="選択中の履歴を、保存済みの完了工程から続行します。確認待ちに未回答があれば再び保留します。検証のみの履歴は登録前まで進みます。",
        ["候補を適用して再開"]="検証済み候補を最新辞書と照合し、新規だけを登録して音声を再生成・再評価します。競合がある場合は登録前で止まります。",
        ["停止"]="変換の停止を要求します。現在のLLM照会等の安全な区切りで停止し、完了済み工程と音声を保持します。後から再開できます。",
        ["回答を保存"]="選択した候補の読み、登録語句、判断理由を保存します。保存だけでは辞書登録・再生成は始まりません。続行には「回答を反映して再開」を押します。",
        ["回答を反映して再開"]="表示中の回答を保存し、保存済みの各回答で採用判断をやり直して続行します。未回答がなければ登録・再生成へ進みます。検証のみの履歴では登録前まで進みます。",
        ["モデル照会を再試行"]="外部モデルへの照会を再実行して、同じ履歴を続行します。原文、一次LLM、ボイス、Whisper条件は変えません。読みが未確定なら確認待ちになります。",
        ["更新"]="保存済み履歴と選択中の実行の最新状態を読み直します。変換は開始しません。",
        ["HTML履歴を開く"]="選択した実行の原文、各工程、判断理由、前後評価、音声をまとめたHTMLを開きます。",
        ["登録前の音声"]="辞書への追加前に生成した音声を再生します。",
        ["登録後の音声"]="辞書の確認・追加後に再生成した音声を再生します。生成していない場合は再生できません。",
        ["設定を保存"]="表示中の接続先・モデル・保存先等を保存し、現在の辞書を再取得します。APIキーは外部設定のまま扱います。既存履歴の原文やボイスは変更しません。",
        ["再読込"]="保存されている設定を表示し直します。画面でまだ保存していない設定変更は破棄されます。",
        ["最新の辞書を取得"]="VoiSonaの現在の登録済み辞書を全件読み直し、重複や競合も表示します。追加候補の確認結果は無効になるため、登録前に再確認してください。",
        ["重複・競合を確認"]="入力した表記と読みを最新の辞書と比較します。新規だけを追加可能とし、既登録は省略、異なる読みは競合として表示します。この操作では追加しません。",
        ["確認した候補を追加"]="確認した新規候補をVoiSonaの辞書へ登録し、読戻して一覧を更新します。辞書が確認時点から変わっていれば再確認を求めます。原文の音声は再生成しません。",
        ["採用"]="この行に表示した採用候補の読みを選び、回答を保存します。保存だけでは登録・再生成は始まりません。全候補を確認した後に「回答を反映して再開」を押します。",
        ["不採用"]="この候補を辞書に登録しない判断へ切り替え、回答を保存します。別の読みが正解と確定した意味ではありません。",
        ["送受信ログを更新"]="選択した実行のLLM送信内容と応答を読み直します。LLMへ新しい照会は送りません。"
    };
    static void SetExplanation(Button button)
    {
        var name=button.Content?.ToString() ?? "";
        var text=Explanations.GetValueOrDefault(name,button.ToolTip is string existing ? existing:"このボタンの操作を実行します。");
        if(button.DataContext is QuestionRow row && name=="採用")text=$"「{row.Label}」の読みを「{row.ProposedReading}」として採用し、回答を保存します。続行には「回答を反映して再開」を押します。";
        if(button.ToolTip is ToolTip {Content:TextBlock block})block.Text=text;
        else button.ToolTip=new ToolTip {Content=new TextBlock {Text=text,TextWrapping=TextWrapping.Wrap,MaxWidth=420}};
        ToolTipService.SetShowOnDisabled(button,true);
        ToolTipService.SetInitialShowDelay(button,250);
        ToolTipService.SetShowDuration(button,60000);
    }
    void ButtonLoaded(object sender,RoutedEventArgs e){if(sender is Button button)SetExplanation(button);}
    void ButtonToolTipOpening(object sender,ToolTipEventArgs e){if(sender is Button button)SetExplanation(button);}
}
