using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json.Nodes;
namespace ReadingRepair.Desktop;

internal sealed class Backend
{
    public string Workspace { get; }
    public string SettingsFile { get; }
    public Backend()
    {
        var args=Environment.GetCommandLineArgs();
        string? Option(string name) { var i=Array.IndexOf(args,name); return i>=0 && i+1<args.Length ? args[i+1] : null; }
        var folder=new DirectoryInfo(AppContext.BaseDirectory);
        while(folder!=null && !File.Exists(Path.Combine(folder.FullName,"tools","PronunciationDictionaryLab","application.py"))) folder=folder.Parent;
        Workspace=Path.GetFullPath(Option("--workspace") ?? Environment.GetEnvironmentVariable("VOISONA_REPAIR_WORKSPACE") ?? folder?.FullName ?? throw new InvalidOperationException("作業フォルダーを指定してください。"));
        SettingsFile=Path.GetFullPath(Option("--settings") ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"VoisonaReadingRepair","settings.json"));
    }
    string Python()
    {
        if(File.Exists(SettingsFile))
        {
            try { var value=JsonNode.Parse(File.ReadAllText(SettingsFile))?["python"]?.GetValue<string>(); if(!string.IsNullOrWhiteSpace(value) && File.Exists(value)) return value; } catch { }
        }
        var path=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","Python","Python312","python.exe");
        return File.Exists(path) ? path : "python";
    }
    public async Task<JsonNode> Call(string command,JsonNode? payload=null,string? job=null,Action<JsonObject>? progress=null,params string[] options)
    {
        var start=new ProcessStartInfo(Python()) { UseShellExecute=false,CreateNoWindow=true,RedirectStandardInput=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardInputEncoding=new UTF8Encoding(false),StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8,WorkingDirectory=Workspace };
        foreach(var arg in new[]{"-X","utf8","-u",Path.Combine(Workspace,"tools","PronunciationDictionaryLab","application.py"),command,"--workspace",Workspace,"--settings",SettingsFile}) start.ArgumentList.Add(arg);
        if(job!=null) { start.ArgumentList.Add("--job");start.ArgumentList.Add(job); }
        if(payload!=null) start.ArgumentList.Add("--stdin");
        foreach(var option in options) start.ArgumentList.Add(option);
        using var process=Process.Start(start) ?? throw new InvalidOperationException("共通処理を起動できませんでした。");
        var errors=process.StandardError.ReadToEndAsync();
        if(payload!=null) await process.StandardInput.WriteAsync(payload.ToJsonString());
        process.StandardInput.Close();
        JsonNode? result=null; string? error=null;
        while(await process.StandardOutput.ReadLineAsync() is { } line)
        {
            JsonObject? item; try { item=JsonNode.Parse(line) as JsonObject; } catch { continue; }
            if(item==null)continue;
            if(item["type"]?.GetValue<string>()=="result") result=item["result"]?.DeepClone();
            else if(item["type"]?.GetValue<string>()=="error") error=item["message"]?.GetValue<string>();
            else progress?.Invoke(item);
        }
        await process.WaitForExitAsync(); await errors;
        if(error!=null)throw new InvalidOperationException(error);
        return result ?? throw new InvalidOperationException("処理結果を取得できませんでした。Pythonと設定を確認してください。");
    }
}
