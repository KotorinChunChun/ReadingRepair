using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.Media;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;

namespace ReadingRepair.Desktop;

public partial class MainWindow : Window
{
    readonly Backend backend;
    readonly SoundPlayer player = new();
    bool busy, refreshing, savingAnswer;
    string? currentId;
    JsonNode? current;
    JsonNode? checkedDictionary;
    readonly ObservableCollection<SettingRow> settings = [];
    static string Text(JsonNode? node) => node?.ToString() ?? "";
    static readonly Dictionary<string,string> States = new()
    {
        ["ready"]="実行準備済み",["running"]="実行中",["stop_requested"]="停止要求済み",["cancelled"]="停止しました",
        ["interrupted"]="中断・再開できます",["pending_confirmation"]="読みの確認待ち",["candidates_ready"]="候補の適用待ち",
        ["completed"]="検証・再評価完了",["failed"]="処理に失敗しました",["dictionary_conflict"]="辞書の読みが競合しています"
    };
    static string State(JsonNode? node) { var text=Text(node);return States.GetValueOrDefault(text,text); }
    static string JobState(JsonNode job)=>Text(job["mode"])=="verify" && Text(job["status"])=="candidates_ready" ? "検証のみ完了":State(job["status"]);
    static readonly Dictionary<string,string> Stages = new()
    {
        ["preflight"]="接続条件の確認",["known-readings"]="登録辞書の取得",["reference-1"]="原文の読みを検討",
        ["before-2-audio"]="登録前の音声を生成",["before-2-talk-analysis"]="登録前の発音を解析",["before-2-whisper"]="登録前の音声を文字起こし",
        ["comparison-1-2"]="読みの食い違いを検出",["secondary-review"]="別モデルへ独立照会",["adjudication"]="読みの採用判断",
        ["reference-adopted"]="採用する読みを反映",["comparison-adopted-before"]="採用基準で登録前を評価",
        ["registration-plan"]="辞書登録の候補を整理",["registration"]="辞書へ登録",["registered-readings"]="登録した辞書を確認",
        ["after-3-audio"]="登録後の音声を生成",["after-3-talk-analysis"]="登録後の発音を解析",["after-3-whisper"]="登録後の音声を文字起こし",
        ["post-secondary-review"]="登録後の別モデル照会と採用判断",
        ["comparison-1-3"]="登録後の読みを評価",["reference-final"]="最終の評価基準を確定",["comparison-final-before"]="最終基準で登録前を確認",
        ["comparison-final-after"]="同じ最終基準で登録後を確認"
    };
    static readonly Dictionary<string,string> SettingLabels = new()
    {
        ["python"]="Python実行ファイル（開発時）",
        ["tts_engine"]="TTSエンジン（voisona / http-wav）",["tts_profile"]="API辞書プロファイル",["tts_env"]="TTS接続の外部設定ファイル",["api_dictionary_file"]="HTTP TTS用JSON辞書",["runs_root"]="検証結果の保存先",
        ["whisper_model"]="Whisperモデル",["whisper_site_packages"]="Whisperライブラリのフォルダー",["reviewer_env"]="外部モデルの設定ファイル",
        ["dictionary_file"]="VoiSonaユーザー辞書",["llm_model"]="一次LLMモデル",["voice"]="ボイス",["voice_version"]="ボイスのバージョン",
        ["gemini_transport"]="Gemini接続方式（api / cli）",["review_timeout"]="外部モデルの待機時間（秒）"
    };

    public MainWindow()
    {
        InitializeComponent();Title=WindowTitle.Create();
        // 既存の左側ウィンドウを動かさず、使用可能な領域の右側へ表示する。
        var work=SystemParameters.WorkArea;
        MinWidth=800;Width=Math.Max(MinWidth,work.Width/2);Height=work.Height;
        Left=work.Right-Width;Top=work.Top;
        backend=new Backend(); SettingsGrid.ItemsSource=settings;

        Closing += (_,e) =>
        {
            if(busy) { e.Cancel=true; _=Safe(RequestStop);StatusText.Text="停止を要求しました。処理の停止後に終了してください。"; }
            else player.Stop();
        };
    }

    internal Task InitializeBackend()=>Safe(async ()=>{await ReloadSettings();await RefreshHistory();await ReloadDictionary();IsReady=true;});
    internal bool IsBusy => busy;
    internal bool IsReady { get; private set; }
    async Task Safe(Func<Task> action)
    {
        try { await action(); }
        catch(Exception ex) { StatusText.Text=ex.Message;MessageBox.Show(this,ex.Message,WindowTitle.Create("確認"),MessageBoxButton.OK,MessageBoxImage.Information); }
    }
    void Busy(bool value)
    {
        busy=value;Progress.IsIndeterminate=value;RepairButton.IsEnabled=!value;VerifyButton.IsEnabled=!value;
        StopButton.IsEnabled=value;SaveSettingsButton.IsEnabled=!value;HistoryGrid.IsEnabled=!value;
        ResumeButton.IsEnabled=!value && currentId!=null && Text(current?["status"])!="completed";
        CheckDictionaryButton.IsEnabled=!value;
        DictionarySurface.IsEnabled=!value;DictionaryReading.IsEnabled=!value;
        AddDictionaryButton.IsEnabled=!value && checkedDictionary?["can_register"]?.GetValue<bool>()==true;
        TestPlaybackButton.IsEnabled=!value && TestAudioKey()!=null;
        Questions.IsEnabled=!value;
    }
    async Task ReloadSettings()
    {
        var values=await backend.Call("settings");settings.Clear();
        foreach(var pair in SettingLabels) settings.Add(new SettingRow {Key=pair.Key,Label=pair.Value,Value=Text(values[pair.Key])});
    }
    async Task RefreshHistory()
    {
        var rows=(await backend.Call("history")).AsArray().OfType<JsonObject>().Select(j=>new HistoryRow
        {
            Id=Text(j["id"]),Label=Text(j["id"]).Replace("reading-repair-",""),State=JobState(j),
            Before=Text(j["before_score"]),After=Text(j["after_score"]),Original=Text(j["original"])
        }).ToList();
        refreshing=true;
        HistoryGrid.ItemsSource=rows;
        HistoryGrid.SelectedItem=rows.FirstOrDefault(r=>r.Id==currentId);
        refreshing=false;
        if(currentId==null && rows.Count>0) { currentId=rows[0].Id;await LoadCurrent(true); }
    }
    async Task LoadCurrent(bool loadText=false)
    {
        if(currentId==null)return;
        var requestedId=currentId;
        var loaded=await backend.Call("status",job:requestedId);
        if(requestedId!=currentId)return;
        current=loaded;
        if(loadText)
        {
            OriginalInput.Text=Text(current["original"]);
            KnownInput.Text=string.Join(Environment.NewLine,current["known_readings"]?.AsArray().Select(r=>$"{Text(r?["surface"])}={Text(r?["reading"])}") ?? []);
        }
        var selected=(Questions.SelectedItem as QuestionRow)?.Id;
        Questions.ItemsSource=current["questions"]?.AsArray().OfType<JsonObject>().Select(q=>
        {
            var answer=current["user_answers"]?.AsArray().FirstOrDefault(a=>Text(a?["id"])==Text(q["id"]));
            var proposed=Text(answer?["reading"]);
            if(proposed.Length==0)proposed=Text(q["primary_readings"]?.AsArray().FirstOrDefault() ?? q["choices"]?.AsArray().FirstOrDefault());
            return new QuestionRow {Id=Text(q["id"]),Label=Text(q["surface"])+"　"+string.Join(" / ",q["choices"]?.AsArray().Select(Text) ?? []),Data=q,ProposedReading=proposed,
                DecisionState=answer==null ? "未回答":Text(answer["action"])=="accept" ? "採用済み："+Text(answer["reading"]):"不採用（登録しない）"};
        }).ToList();
        Questions.SelectedItem=Questions.Items.Cast<QuestionRow>().FirstOrDefault(q=>q.Id==selected) ?? Questions.Items.Cast<QuestionRow>().FirstOrDefault();
        ResumeButton.Content=Text(current["status"])=="candidates_ready" ? "候補を適用して再開" : "選択した実行を再開";
        StatusText.Text=JobState(current);
        if(current["summary"] is {} summary) StatusText.Text+=$"　登録前 {Text(summary["before"]?["llm_score"])}点 → 登録後 {Text(summary["after"]?["llm_score"])}点";
        else if(current["before_score"]!=null) StatusText.Text+=$"　登録前 {Text(current["before_score"])}点"+(Text(current["status"])=="pending_confirmation" ? "（暫定）":"");
        if(current["error_type"]!=null)StatusText.Text+="　"+Text(current["error_type"]);
        if(current["message"]!=null)StatusText.Text+="　"+Text(current["message"]);
        CandidateChecks.ItemsSource=CheckRows(current["dictionary_precheck"]);
        ProgressLog.Text=Text(current["progress"]?["text"]);ProgressLog.ScrollToEnd();
        if(Tabs.SelectedItem==LlmTab)await ReloadLlmLogs();
        if(!busy) Busy(false);
    }
    JsonArray KnownReadings()
    {
        var result=new JsonArray();
        foreach(var line in KnownInput.Text.Split('\n').Select(x=>x.Trim()).Where(x=>x.Length>0))
        {
            var parts=line.Split('=',2);
            if(parts.Length!=2)throw new InvalidOperationException("指定読みは、1行ごとに 表記=カタカナ読み で入力してください。");
            result.Add(new JsonObject { ["surface"]=parts[0].Trim(),["reading"]=parts[1].Trim() });
        }
        return result;
    }
    async Task Start(string mode)
    {
        if(busy)return;
        var request=new JsonObject { ["text"]=OriginalInput.Text,["known_readings"]=KnownReadings(),["mode"]=mode };
        Busy(true);
        try
        {
            current=await backend.Call("create",request);currentId=Text(current["id"]);ProgressLog.Clear();
            await Execute(false,false);
        }
        finally { Busy(false); }
    }
    void ProgressEvent(JsonObject item)
    {
        Dispatcher.Invoke(() =>
        {
            var stage=Text(item["stage"]); if(stage.Length==0)return;
            var label=Stages.GetValueOrDefault(stage,"検証処理");
            if(item["display"]!=null)
            {
                ProgressLog.AppendText(Text(item["display"])+"\n");ProgressLog.ScrollToEnd();
                StatusText.Text=Text(item["state"])=="detail" ? label : Text(item["message"]);return;
            }
            var state=Text(item["state"])=="completed" ? "完了" : "実行中";
            ProgressLog.AppendText($"{DateTime.Now:HH:mm:ss}　{label}：{state}\n");ProgressLog.ScrollToEnd();StatusText.Text=label;
        });
    }
    async Task Execute(bool retry,bool apply)
    {
        if(currentId==null)return;
        Busy(true);StatusText.Text="変換しています。";
        try
        {
            var options=new List<string>();if(retry)options.Add("--retry-reviewers");if(apply)options.Add("--apply");
            current=await backend.Call("execute",job:currentId,progress:ProgressEvent,options:options.ToArray());
            await LoadCurrent();await RefreshHistory();await ReloadDictionary();
            if(Text(current["status"])=="pending_confirmation")Tabs.SelectedIndex=1;
        }
        finally { Busy(false); }
    }
    async Task RequestStop()
    {
        if(currentId==null || !busy)return;
        await backend.Call("stop",job:currentId);StopButton.IsEnabled=false;
        StatusText.Text="停止要求済み。現在の処理の終了後に停止します。";
    }
    async Task Resume(bool retry)
    {
        if(busy)return;
        await Execute(retry,Text(current?["status"])=="candidates_ready");
    }
    async Task SaveAnswer()
    {
        if(busy)throw new InvalidOperationException("処理が停止してから回答してください。");
        if(currentId==null || Questions.SelectedItem is not QuestionRow question)throw new InvalidOperationException("確認する候補を選択してください。");
        if(Decision.SelectedIndex==0)throw new InvalidOperationException("採用または登録しないを選択してください。");
        var answer=new JsonObject { ["id"]=question.Id,["surface"]=Text(question.Data["surface"]),["action"]=Decision.SelectedIndex==1 ? "accept":"reject",["reading"]=ChosenReading.Text.Trim(),["reason"]=DecisionReason.Text.Trim() };
        if(RegistrationSurface.Text.Trim().Length>0 || RegistrationReading.Text.Trim().Length>0)
            answer["registration"]=new JsonObject { ["surface"]=RegistrationSurface.Text.Trim(),["reading"]=RegistrationReading.Text.Trim() };
        await backend.Call("answer",new JsonObject { ["answers"]=new JsonArray(answer) },currentId);
        await LoadCurrent();
        var ids=current?["questions"]?.AsArray().Select(q=>Text(q?["id"])).ToHashSet() ?? [];
        var count=current?["user_answers"]?.AsArray().Count(a=>ids.Contains(Text(a?["id"]))) ?? 0;
        StatusText.Text=$"回答を保存しました（{count}/{ids.Count}件）。「回答を反映して再開」で続行します。";
    }

    async Task QuickDecision(object sender,bool accept)
    {
        if(busy || savingAnswer || sender is not Button {DataContext:QuestionRow row})return;
        savingAnswer=true;
        try
        {
            Questions.SelectedItem=row;
            Decision.SelectedIndex=accept ? 1:2;ChosenReading.Text=accept ? row.ProposedReading:"";
            if(!accept){RegistrationSurface.Clear();RegistrationReading.Clear();}
            DecisionReason.Text=accept ? $"候補一覧で「{row.ProposedReading}」を利用者が採用しました。":"候補一覧で利用者が不採用（辞書へ登録しない）を選びました。";
            await SaveAnswer();
        }
        finally {savingAnswer=false;}
    }
    async void QuickAccept_Click(object sender,RoutedEventArgs e)=>await Safe(()=>QuickDecision(sender,true));
    async void QuickReject_Click(object sender,RoutedEventArgs e)=>await Safe(()=>QuickDecision(sender,false));

    void Questions_SelectionChanged(object sender,SelectionChangedEventArgs e)
    {
        if(Questions.SelectedItem is not QuestionRow question)
        {
            QuestionContext.Clear();Opinions.Clear();Decision.SelectedIndex=0;
            ChosenReading.ItemsSource=null;ChosenReading.Text="";RegistrationSurface.Clear();RegistrationReading.Clear();DecisionReason.Clear();return;
        }
        var q=question.Data;QuestionContext.Text=Text(q["context"]);
        var providerStates=new Dictionary<string,string> { ["ok"]="応答取得",["unavailable"]="照会失敗",["disabled"]="無効",["not_configured"]="キー未設定" };
        var tts=string.Join(" / ",q["tts_readings"]?.AsArray().Select(Text) ?? []);
        var explanation=Text(q["tts_status"]) switch {"recalculated"=>"保存済みTTS解析を再照合", "unsupported"=>"選択したエンジンは発音解析に非対応。Whisperの結果を参照してください。","unmapped"=>"解析は取得済みですが対象語に対応づけできません", "not_recorded"=>"TTS解析が未取得",_=>"TTS解析の発音"};
        var lines=new List<string> {$"一次LLMの仮説（{Text(q["primary_model"])}）："+string.Join(" / ",q["primary_readings"]?.AsArray().Select(Text) ?? []),$"TTSの発音：{(tts.Length>0 ? tts:"未確定")}（{explanation}）"};
        lines.Add("Whisperの文字起こし："+(q["whisper_recorded"]?.GetValue<bool>()==true ? Text(q["whisper_text"]):"未実施"));
        lines.AddRange(q["opinions"]?.AsArray().Select(p=>$"{Text(p?["provider"])}（{Text(p?["model"])}）：{Text(p?["opinion"]?["reading"])}　{Text(p?["opinion"]?["reason"])}（{providerStates.GetValueOrDefault(Text(p?["status"]),Text(p?["status"]))}{(p?["http_status"]!=null ? " HTTP "+Text(p["http_status"]):"")}）") ?? []);
        lines.AddRange(q["votes"]?.AsArray().Select(v=>$"有効票：{Text(v?["provider"])} → {Text(v?["reading"])}") ?? []);
        lines.AddRange(q["abstentions"]?.AsArray().Select(v=>$"棄権：{Text(v?["provider"])}（{Text(v?["reason"])}）") ?? []);
        lines.Add("判定理由："+Text(q["reason"]));
        Opinions.Text=string.Join(Environment.NewLine,lines);
        ChosenReading.ItemsSource=q["choices"]?.AsArray().Select(Text).ToList();ChosenReading.Text="";
        Decision.SelectedIndex=0;DecisionReason.Clear();RegistrationSurface.Clear();RegistrationReading.Clear();
        var saved=current?["user_answers"]?.AsArray().FirstOrDefault(a=>Text(a?["id"])==question.Id);
        if(saved!=null)
        {
            Decision.SelectedIndex=Text(saved["action"])=="accept" ? 1:2;ChosenReading.Text=Text(saved["reading"]);DecisionReason.Text=Text(saved["reason"]);
            RegistrationSurface.Text=Text(saved["registration"]?["surface"]);RegistrationReading.Text=Text(saved["registration"]?["reading"]);
        }
    }
    async void History_SelectionChanged(object sender,SelectionChangedEventArgs e)
    {
        if(refreshing || busy || HistoryGrid.SelectedItem is not HistoryRow row)return;
        await Safe(async ()=>{currentId=row.Id;await LoadCurrent(true);});
    }
    async void Doctor_Click(object sender,RoutedEventArgs e) => await Safe(async ()=>
    {
        StatusText.Text="依存を診断しています。";var result=await backend.Call("doctor");
        var grid=new DataGrid {IsReadOnly=true,Margin=new Thickness(16),AutoGenerateColumns=false};
        grid.Columns.Add(new DataGridTextColumn {Header="項目",Binding=new System.Windows.Data.Binding("Name"),Width=190});
        grid.Columns.Add(new DataGridTextColumn {Header="状態",Binding=new System.Windows.Data.Binding("State"),Width=85});
        grid.Columns.Add(new DataGridTextColumn {Header="内容",Binding=new System.Windows.Data.Binding("Detail"),Width=new DataGridLength(1,DataGridLengthUnitType.Star)});
        grid.ItemsSource=result["checks"]?.AsArray().Select(c=>new DiagnosticRow {Name=Text(c?["name"]),State=Text(c?["status"]),Detail=Text(c?["detail"])}).ToList();
        var window=new Window {Title="依存の診断",Owner=this,Width=940,Height=550,Content=grid,WindowStartupLocation=WindowStartupLocation.CenterOwner};window.ShowDialog();
        StatusText.Text=result["ready"]?.GetValue<bool>()==true ? "診断完了：実行できます。":"診断完了：設定を確認してください。";
    });
    async void Repair_Click(object sender,RoutedEventArgs e)=>await Safe(()=>Start("repair"));
    async void Verify_Click(object sender,RoutedEventArgs e)=>await Safe(()=>Start("verify"));
    async void Resume_Click(object sender,RoutedEventArgs e)=>await Safe(()=>Resume(false));
    async void Stop_Click(object sender,RoutedEventArgs e)=>await Safe(RequestStop);
    async void SaveAnswer_Click(object sender,RoutedEventArgs e)=>await Safe(SaveAnswer);
    async void AnswerResume_Click(object sender,RoutedEventArgs e)=>await Safe(async ()=>{await SaveAnswer();await Execute(false,false);});
    async void Retry_Click(object sender,RoutedEventArgs e)=>await Safe(()=>Resume(true));
    async void Refresh_Click(object sender,RoutedEventArgs e)=>await Safe(async ()=>{await RefreshHistory();await LoadCurrent();});
    async void ReloadSettings_Click(object sender,RoutedEventArgs e)=>await Safe(ReloadSettings);
    async void SaveSettings_Click(object sender,RoutedEventArgs e)=>await Safe(async ()=>
    {
        SettingsGrid.CommitEdit(DataGridEditingUnit.Cell,true);SettingsGrid.CommitEdit(DataGridEditingUnit.Row,true);
        var data=new JsonObject();foreach(var item in settings) data[item.Key]=item.Key=="review_timeout" ? JsonValue.Create(int.Parse(item.Value)) : JsonValue.Create(item.Value);
        await backend.Call("save-settings",data);await ReloadDictionary();StatusText.Text="設定を保存しました。";
    });

    static string DictionaryState(JsonNode? node)=>Text(node) switch {"registered"=>"登録済み","new"=>"新規","already_registered"=>"登録済み","duplicate"=>"辞書内で重複","duplicate_candidate"=>"候補内で重複","conflict"=>"読みが競合",_=>Text(node)};
    static List<DictionaryCheckRow> CheckRows(JsonNode? data)=>data?["entries"]?.AsArray().Select(row=>new DictionaryCheckRow {Surface=Text(row?["surface"]),Reading=Text(row?["reading"]),State=DictionaryState(row?["state"]),Existing=string.Join(" / ",row?["existing_readings"]?.AsArray().Select(Text) ?? [])}).ToList() ?? [];
    void InvalidateDictionaryCheck()
    {
        checkedDictionary=null;
        if(AddDictionaryButton!=null)AddDictionaryButton.IsEnabled=false;
        if(DictionaryChecks!=null)DictionaryChecks.ItemsSource=null;
    }
    void DictionaryCandidate_Changed(object sender,TextChangedEventArgs e)=>InvalidateDictionaryCheck();
    async Task ReloadDictionary()
    {
        InvalidateDictionaryCheck();
        var data=await backend.Call("dictionary");
        DictionaryGrid.ItemsSource=data["entries"]?.AsArray().Select(row=>new DictionaryRow {Priority=Text(row?["priority"]),Surface=Text(row?["surface"]),Reading=Text(row?["reading"]),Accent=Text(row?["accent"]),State=DictionaryState(row?["state"])}).ToList();
        DictionarySummary.Text=$"{data["entries"]?.AsArray().Count ?? 0}件　重複・競合 {data["issues"]?.AsArray().Count ?? 0}件";
        DictionarySummary.ToolTip=Text(data["dictionary_file"]);
    }
    JsonObject DictionaryRequest()=>new() {["entries"]=new JsonArray(new JsonObject {["surface"]=DictionarySurface.Text.Trim(),["reading"]=DictionaryReading.Text.Trim()})};
    async void DictionaryRefresh_Click(object sender,RoutedEventArgs e)=>await Safe(ReloadDictionary);
    async void DictionaryCheck_Click(object sender,RoutedEventArgs e)=>await Safe(async ()=>
    {
        if(busy)return;
        Busy(true);
        try
        {
            await ReloadDictionary();checkedDictionary=await backend.Call("check-dictionary",DictionaryRequest());
            DictionaryChecks.ItemsSource=CheckRows(checkedDictionary);
            StatusText.Text=checkedDictionary["has_conflicts"]?.GetValue<bool>()==true ? "読みが競合しています。既存の辞書は上書きしません。":checkedDictionary["can_register"]?.GetValue<bool>()==true ? "新規の候補です。追加できます。":"同じ表記と読みが登録済みです。";
        }
        finally {Busy(false);}
    });
    async void DictionaryAdd_Click(object sender,RoutedEventArgs e)=>await Safe(async ()=>
    {
        if(busy || checkedDictionary?["can_register"]?.GetValue<bool>()!=true)return;
        var request=DictionaryRequest();request["dictionary_sha256"]=Text(checkedDictionary["dictionary_sha256"]);
        Busy(true);
        try
        {
            var result=await backend.Call("add-dictionary",request);await ReloadDictionary();
            DictionaryChecks.ItemsSource=CheckRows(result["precheck"]);
            StatusText.Text=Text(result["status"]) switch {"registered"=>"ユーザー辞書へ追加しました。","already_registered"=>"同じ表記と読みが登録済みです。","dictionary_changed"=>"辞書が変更されました。候補を再確認してください。",_=>"読みが競合しています。追加していません。"};
        }
        finally {Busy(false);}
    });
    async Task ReloadLlmLogs()
    {
        if(currentId==null){LlmCalls.ItemsSource=null;LlmMetadata.Text="履歴から実行を選択してください。";return;}
        var selected=(LlmCalls.SelectedItem as LlmCallRow)?.Id;
        var requestedId=currentId;
        var result=await backend.Call("llm-log",job:requestedId);
        if(requestedId!=currentId)return;
        LlmCalls.ItemsSource=result["calls"]?.AsArray().OfType<JsonObject>().Select(row=>new LlmCallRow {Id=Text(row["id"]),Data=row,
            Label=$"{Text(row["provider"])}　{Text(row["model"])}\n{Stages.GetValueOrDefault(Text(row["stage"]),Text(row["stage"]))}　{LlmStatus(row["status"])}"}).ToList();
        LlmCalls.SelectedItem=LlmCalls.Items.Cast<LlmCallRow>().FirstOrDefault(row=>row.Id==selected) ?? LlmCalls.Items.Cast<LlmCallRow>().FirstOrDefault();
        if(LlmCalls.Items.Count==0){LlmMetadata.Text="この実行にはLLM送受信の記録がありません。";LlmRequest.Clear();LlmResponse.Clear();}
    }
    async void LlmRefresh_Click(object sender,RoutedEventArgs e)=>await Safe(ReloadLlmLogs);
    static string LlmStatus(JsonNode? node)=>Text(node) switch {"ok"=>"応答取得","running"=>"送受信中","unavailable"=>"照会失敗","failed"=>"失敗","cancelled"=>"停止","not_configured"=>"キー未設定","disabled"=>"無効","saved"=>"旧記録",_=>Text(node)};
    async void Tabs_SelectionChanged(object sender,SelectionChangedEventArgs e)
    {
        if(e.OriginalSource==Tabs && Tabs.SelectedItem==LlmTab)await Safe(ReloadLlmLogs);
    }
    void LlmCall_SelectionChanged(object sender,SelectionChangedEventArgs e)
    {
        if(LlmCalls.SelectedItem is not LlmCallRow row)return;
        var data=row.Data;
        var requestKind=Text(data["request_kind"]) switch {"actual_prompt"=>"実際に送信したプロンプト","saved_prompt"=>"旧記録の保存済みプロンプト","not_sent"=>"未送信",_=>"保存済み入力からの復元"};
        var responseKind=Text(data["response_kind"]) switch {"raw_text"=>"受信した本文","parsed_json"=>"受信応答を解析したJSON","validated_result"=>"旧記録の検証済み応答",_=>"受信なし"};
        LlmMetadata.Text=$"{Text(data["provider"])} ／ {Text(data["model"])} ／ {LlmStatus(data["status"])}\n{requestKind} ／ {responseKind}\n{Text(data["started_at"])}　{Text(data["error_type"])}{(data["http_status"]!=null ? " HTTP "+Text(data["http_status"]):"")}";
        LlmRequest.Text=Text(data["request"]);if(LlmRequest.Text.Length==0)LlmRequest.Text="送信なし。キー未設定・無効の場合は照会していません。";
        LlmResponse.Text=Text(data["response"]);if(LlmResponse.Text.Length==0)LlmResponse.Text="応答本文はありません。上の状態・エラー種別を確認してください。";
    }
    void LoadText_Click(object sender,RoutedEventArgs e)
    {
        if(busy)return;
        var dialog=new Microsoft.Win32.OpenFileDialog {Filter="文章ファイル|*.txt;*.md|すべてのファイル|*.*"};
        if(dialog.ShowDialog(this)==true) _=Safe(()=>{OriginalInput.Text=File.ReadAllText(dialog.FileName);return Task.CompletedTask;});
    }
    void Report_Click(object sender,RoutedEventArgs e)=>_=Safe(()=>
    {
        var path=Text(current?["report"]);if(!File.Exists(path))throw new InvalidOperationException("履歴から記録のある実行を選択してください。");
        Process.Start(new ProcessStartInfo(path){UseShellExecute=true});return Task.CompletedTask;
    });
    void Play(string key)
    {
        var file=Text(current?[key]);if(!File.Exists(file))throw new InvalidOperationException("この段階の音声はまだ生成されていません。");
        player.Stop();player.SoundLocation=file;player.Play();
        StatusText.Text=key=="audio_before" ? "登録前の音声を再生しています。":"登録後の音声を再生しています。";
    }
    string? TestAudioKey()=>File.Exists(Text(current?["audio_after"])) ? "audio_after" : File.Exists(Text(current?["audio_before"])) ? "audio_before" : null;
    void TestPlayback_Click(object sender,RoutedEventArgs e)=>_=Safe(()=>
    {
        var key=TestAudioKey() ?? throw new InvalidOperationException("音声の生成後にテスト再生できます。");
        Play(key);return Task.CompletedTask;
    });
    void PlayBefore_Click(object sender,RoutedEventArgs e)=>_=Safe(()=>{Play("audio_before");return Task.CompletedTask;});
    void PlayAfter_Click(object sender,RoutedEventArgs e)=>_=Safe(()=>{Play("audio_after");return Task.CompletedTask;});
    void StopAudio_Click(object sender,RoutedEventArgs e)=>player.Stop();
}

public sealed class SettingRow {public string Key {get;set;}="";public string Label {get;set;}="";public string Value {get;set;}="";}
public sealed class QuestionRow {public string Id {get;set;}="";public string Label {get;set;}="";public JsonObject Data {get;set;}=new();public string ProposedReading {get;set;}="";public string ProposalLabel=>"採用する読み："+ProposedReading;public string DecisionState {get;set;}="";}
public sealed class HistoryRow {public string Id {get;set;}="";public string Label {get;set;}="";public string State {get;set;}="";public string Before {get;set;}="";public string After {get;set;}="";public string Original {get;set;}="";}
public sealed class DiagnosticRow {public string Name {get;set;}="";public string State {get;set;}="";public string Detail {get;set;}="";}
public sealed class DictionaryRow {public string Priority {get;set;}="";public string Surface {get;set;}="";public string Reading {get;set;}="";public string Accent {get;set;}="";public string State {get;set;}="";}
public sealed class DictionaryCheckRow {public string Surface {get;set;}="";public string Reading {get;set;}="";public string State {get;set;}="";public string Existing {get;set;}="";}
public sealed class LlmCallRow {public string Id {get;set;}="";public string Label {get;set;}="";public JsonObject Data {get;set;}=new();}
