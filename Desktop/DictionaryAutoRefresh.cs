using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace ReadingRepair.Desktop;

// CLIのexclusive()と同じ辞書別OSロックを使い、更新途中の一覧を表示しない。
internal sealed class DictionaryAutoRefresh(Func<Task<JsonNode>> load, Action<JsonNode> apply) : IDisposable
{
    string? path, displayedHash;
    bool running, disposed;
    public void SetPath(string value)
    {
        var next=Path.GetFullPath(value);
        if(!string.Equals(next,path,StringComparison.OrdinalIgnoreCase)){path=next;displayedHash=null;}
    }
    static FileStream? TryLock(string dictionary)
    {
        // PythonのWindows normcase(resolve())に合わせる。リンク先も既存ファイルの実パスで解決する。
        var normalized=CanonicalPath(dictionary).ToLowerInvariant();
        var name=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(normalized))).ToLowerInvariant()[..24]+".lock";
        var local=Environment.GetEnvironmentVariable("LOCALAPPDATA") ?? Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var folder=Path.Combine(local,"ReadingRepair","locks");
        Directory.CreateDirectory(folder);
        var stream=new FileStream(Path.Combine(folder,name),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.ReadWrite);
        try
        {
            if(stream.Length==0){stream.WriteByte(48);stream.Flush();}
            stream.Lock(0,1);return stream;
        }
        catch(IOException){stream.Dispose();return null;}
        catch{stream.Dispose();throw;}
    }
    static string CanonicalPath(string value)
    {
        var full=Path.GetFullPath(value);
        if(!File.Exists(full))return full;
        using var file=File.OpenHandle(full,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete);
        var buffer=new StringBuilder(32768);
        var length=GetFinalPathNameByHandle(file,buffer,(uint)buffer.Capacity,0);
        if(length==0 || length>=buffer.Capacity)throw new IOException("辞書の実パスを取得できません。");
        var resolved=buffer.ToString();
        if(resolved.StartsWith(@"\\?\UNC\",StringComparison.OrdinalIgnoreCase))return @"\\"+resolved[8..];
        return resolved.StartsWith(@"\\?\",StringComparison.Ordinal) ? resolved[4..] : resolved;
    }
    [System.Runtime.InteropServices.DllImport("kernel32.dll",CharSet=System.Runtime.InteropServices.CharSet.Unicode,SetLastError=true)]
    static extern uint GetFinalPathNameByHandle(Microsoft.Win32.SafeHandles.SafeFileHandle file,StringBuilder path,uint length,uint flags);
    public async Task<bool> RefreshAsync(bool force=false)
    {
        if(disposed || running || path==null)return false;
        running=true;
        try
        {
            var requestedPath=path;
            using var guard=TryLock(requestedPath);
            if(guard==null)return false;
            var hash=File.Exists(requestedPath) ? Convert.ToHexString(SHA256.HashData(await File.ReadAllBytesAsync(requestedPath))).ToLowerInvariant() : "";
            if(!force && displayedHash==hash)return false;
            var data=await load();
            if(disposed || !string.Equals(requestedPath,path,StringComparison.OrdinalIgnoreCase))return false;
            apply(data);displayedHash=data["dictionary_sha256"]?.ToString();
            return true;
        }
        finally {running=false;}
    }
    public void Dispose()=>disposed=true;
}
