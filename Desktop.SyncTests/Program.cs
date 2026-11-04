using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using ReadingRepair.Desktop;

internal static class Program
{
    static string Option(string name){var args=Environment.GetCommandLineArgs();return args[Array.IndexOf(args,name)+1];}
    static string Root=>Option("--workspace");
    static string Settings=>Option("--settings");
    static string TestRoot=>Path.GetDirectoryName(Settings)!;
    static string? Optional(string name){var args=Environment.GetCommandLineArgs();var i=Array.IndexOf(args,name);return i>=0 && i+1<args.Length ? args[i+1] : null;}
    static string Python=>Optional("--python") ?? Path.Combine(Root,".venv","Scripts","python.exe");
    static string LockBackend=>Optional("--lock-backend") ?? Path.Combine(Root,"backend");
    static int assertions;
    static void Check(bool ok,string reason){if(!ok)throw new Exception(reason);assertions++;}
    static async Task<JsonNode> Cli(string command,JsonNode? input=null)
    {
        var bundled=Path.Combine(Root,"backend","ReadingRepair.Backend.exe");
        var start=new ProcessStartInfo(File.Exists(bundled) ? bundled : Python){UseShellExecute=false,CreateNoWindow=true,RedirectStandardInput=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=Encoding.UTF8,StandardInputEncoding=new UTF8Encoding(false)};
        if(!File.Exists(bundled))foreach(var arg in new[]{"-X","utf8",Path.Combine(Root,"backend","application.py")})start.ArgumentList.Add(arg);
        foreach(var arg in new[]{command,"--settings",Settings,"--workspace",Root})start.ArgumentList.Add(arg);
        if(input!=null)start.ArgumentList.Add("--stdin");
        using var process=Process.Start(start)!;
        var output=process.StandardOutput.ReadToEndAsync();var error=process.StandardError.ReadToEndAsync();
        if(input!=null)await process.StandardInput.WriteAsync(input.ToJsonString());process.StandardInput.Close();
        await process.WaitForExitAsync();var text=await output;await error;
        if(process.ExitCode!=0)throw new Exception("隔離CLI失敗: "+text);
        return JsonNode.Parse(text.Split('\n',StringSplitOptions.RemoveEmptyEntries).Last())!["result"]!;
    }
    static async Task Until(Func<bool> done,string reason)
    {
        var deadline=DateTime.UtcNow.AddSeconds(15);
        while(!done() && DateTime.UtcNow<deadline)await Task.Delay(100);
        Check(done(),reason);
    }
    static async Task Add(string surface,string reading)
    {
        var payload=new JsonObject {["entries"]=new JsonArray(new JsonObject {["surface"]=surface,["reading"]=reading})};
        var check=await Cli("check-dictionary",payload);payload["dictionary_sha256"]=check["dictionary_sha256"]!.ToString();
        Check((await Cli("add-dictionary",payload))["status"]!.ToString()=="registered","別プロセスのCLI辞書登録");
    }
    static async Task Run()
    {
        if(File.Exists(Settings))throw new Exception("新しい隔離出力先を指定してください。");
        Directory.CreateDirectory(TestRoot);
        var dictionary=Path.Combine(TestRoot,"dictionary.json");
        await File.WriteAllTextAsync(dictionary,"{\"format\":\"readingrepair.dictionary.v1\",\"entries\":[]}");
        var env=Path.Combine(TestRoot,"tts.env");await File.WriteAllTextAsync(env,"TTS_URL=http://127.0.0.1:1/tts\n");
        await Cli("save-settings",new JsonObject {["tts_engine"]="http-wav",["api_dictionary_file"]=dictionary,["tts_env"]=env,["runs_root"]=Path.Combine(TestRoot,"runs")});
        var window=new MainWindow();
        var initialize=(Task)typeof(MainWindow).GetMethod("InitializeBackend",BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(window,null)!;
        await initialize;
        var grid=(DataGrid)window.FindName("DictionaryGrid");
        var surface=(TextBox)window.FindName("DictionarySurface");var reading=(TextBox)window.FindName("DictionaryReading");
        var add=(Button)window.FindName("AddDictionaryButton");
        Check(grid.Items.Count==0,"WPF一覧の初期件数");
        surface.Text="候補";reading.Text="コウホ";
        ((Button)window.FindName("CheckDictionaryButton")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        await Until(()=>add.IsEnabled,"候補の確認完了");
        await Add("認証値","ニンショウチ");
        await Until(()=>grid.Items.Count==1,"手動操作なしで実WPF一覧へCLI追加を反映");
        Check(surface.Text=="候補" && reading.Text=="コウホ","入力中の候補を保持");
        Check(!add.IsEnabled,"旧辞書に対する候補確認を無効化");
        // ロック保持中に有効な途中辞書を書いても一覧には反映しない。
        var lockScript=Path.Combine(TestRoot,"hold.py");
        await File.WriteAllTextAsync(lockScript,"import sys,time\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\nfrom application import Application,exclusive\nimport lab,tts_backends\na=Application(settings_file=sys.argv[2])\nwith exclusive(a.lock_file()):\n p=tts_backends.dictionary_path(a.settings())\n d=lab.load(p)\n d['entries'].append({'surface':'平文','reading':'ヒラブン'})\n lab.save(p,d)\n Path(sys.argv[3]).write_text('held')\n while not Path(sys.argv[4]).exists(): time.sleep(.05)\n");
        var held=Path.Combine(TestRoot,"held");var release=Path.Combine(TestRoot,"release");
        var psi=new ProcessStartInfo(Python){UseShellExecute=false,CreateNoWindow=true};
        foreach(var arg in new[]{"-X","utf8",lockScript,LockBackend,Settings,held,release})psi.ArgumentList.Add(arg);
        using(var process=Process.Start(psi)!)
        {
            try
            {
                await Until(()=>File.Exists(held),"別プロセスのCLIロックを取得");
                await Task.Delay(4500);Check(grid.Items.Count==1,"CLI処理途中の辞書を表示しない");
            }
            finally {await File.WriteAllTextAsync(release,"release");await process.WaitForExitAsync();}
        }
        await Until(()=>grid.Items.Count==2,"CLIロック解放後に反映");
        var original=await File.ReadAllTextAsync(dictionary);
        await File.WriteAllTextAsync(dictionary,"{");await Task.Delay(4500);
        Check(grid.Items.Count==2,"読取失敗時は旧一覧を保持");
        await File.WriteAllTextAsync(dictionary,original);await Add("複数人","フクスウニン");
        await Until(()=>grid.Items.Count==3,"読取失敗後も自動で再試行");
        var stamp=File.GetLastWriteTimeUtc(dictionary);var bytes=await File.ReadAllBytesAsync(dictionary);
        var changed=Encoding.UTF8.GetString(bytes).Replace("ヒラブン","ヘイブン");
        Check(Encoding.UTF8.GetByteCount(changed)==bytes.Length,"同サイズの変更を用意");
        await File.WriteAllTextAsync(dictionary,changed,new UTF8Encoding(false));File.SetLastWriteTimeUtc(dictionary,stamp);
        await Until(()=>grid.Items.Cast<object>().Any(row=>row.GetType().GetProperty("Reading")!.GetValue(row)?.ToString()=="ヘイブン"),"サイズ・日時が同じ変更もSHAで検知");
        window.Close();await Add("拡張子","カクチョウシ");await Task.Delay(2500);
        Check(grid.Items.Count==3,"終了後に一覧を更新しない");
        Console.WriteLine(new JsonObject {["complete"]=true,["assertions"]=assertions,["externalCli"]=true,["actualWpfTree"]=true,["nativeDictionaryModified"]=false}.ToJsonString());
    }
    [STAThread]
    static int Main()
    {
        var app=new System.Windows.Application {ShutdownMode=ShutdownMode.OnExplicitShutdown};
        SynchronizationContext.SetSynchronizationContext(new DispatcherSynchronizationContext());
        var exit=1;
        app.Dispatcher.BeginInvoke(async ()=>{try {await Run();exit=0;}catch(Exception error){Console.Error.WriteLine(error);}finally{app.Shutdown();}});
        app.Run();return exit;
    }
}
