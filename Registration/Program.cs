using System.Diagnostics;
using System.Text.Json;
using System.Windows.Automation;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.IO;

internal static class Program
{
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern nint SendMessageTimeout(nint hwnd, uint msg, nint wParam, nint lParam, uint flags, uint timeout, out nint result);
    static void SendMessage(nint hwnd, uint msg, nint wParam, nint lParam)
    {
        if (SendMessageTimeout(hwnd, msg, wParam, lParam, 0x2, 2000, out _) == 0)
            throw new TimeoutException("VoiSonaへのメッセージが時間切れになりました。");
    }
    [StructLayout(LayoutKind.Sequential)]
    struct Point { public int X; public int Y; }
    [DllImport("user32.dll")] static extern bool ScreenToClient(nint hwnd, ref Point point);
    [DllImport("user32.dll")] static extern nint SetProcessDpiAwarenessContext(nint context);
    [DllImport("user32.dll")] static extern bool IsIconic(nint hwnd);
    [DllImport("user32.dll")] static extern bool ShowWindowAsync(nint hwnd, int command);
    record Entry(string Surface, string Reading);
    record Plan(string Original, Entry[] Entries);
    static readonly JsonSerializerOptions JsonOptions = new() { PropertyNameCaseInsensitive = true, PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true };

    static void Validate(Plan plan)
    {
        if (string.IsNullOrWhiteSpace(plan.Original) || plan.Entries.Length > 20) throw new InvalidOperationException("原文または登録件数が不正です。");
        var seen = new HashSet<string>();
        foreach (var entry in plan.Entries)
        {
            if (string.IsNullOrEmpty(entry.Surface) || entry.Surface.Length > 80 || !plan.Original.Contains(entry.Surface, StringComparison.Ordinal) || Regex.IsMatch(entry.Surface, "[\\s\\[\\]\\\"=,]")) throw new InvalidOperationException("登録表記が不正、または原文にありません。");
            if (string.IsNullOrEmpty(entry.Reading) || entry.Reading.Length > 160 || !Regex.IsMatch(entry.Reading, "^[ァ-ヺー]+$")) throw new InvalidOperationException("発音は全角カタカナで指定してください。");
            if (!seen.Add(StorageSurface(entry.Surface))) throw new InvalidOperationException("同じ表記の候補が重複しています。");
        }
    }

    static string StorageSurface(string surface) => string.Concat(surface.Select(c => char.IsAsciiLetterOrDigit(c) ? (char)(c + 0xFEE0) : c));

    static T ReadWithRetry<T>(Func<T> read)
    {
        for (var attempt = 0; ; attempt++)
        {
            try { return read(); }
            catch (IOException) when (attempt < 30) { Thread.Sleep(50); }
        }
    }

    static Dictionary<string, string> ReadDictionary(string path)
    {
        var result = new Dictionary<string, string>();
        var text = ReadWithRetry(() =>
        {
            if (!File.Exists(path)) throw new FileNotFoundException("VoiSonaの既存辞書ファイルがありません。", path);
            return File.ReadAllText(path, Encoding.UTF8);
        });
        foreach (var line in text.Split('\n'))
        {
            if (string.IsNullOrWhiteSpace(line) || line.StartsWith('#')) continue;
            var match = Regex.Match(line, "^(.*?) \\[([^\\]]+)\\] ");
            if (!match.Success) throw new InvalidOperationException("既存辞書の形式を確認できません。");
            result.TryAdd(match.Groups[1].Value, match.Groups[2].Value);
        }
        return result;
    }

    static string? ExistingReading(Dictionary<string, string> existing, Entry entry)
    {
        var keys = new[] { entry.Surface, StorageSurface(entry.Surface) }.Distinct();
        string? found = null;
        foreach (var key in keys)
            if (existing.TryGetValue(key, out var reading))
            {
                if (reading != entry.Reading) throw new InvalidOperationException("既存の読みと競合しています: " + entry.Surface);
                found = reading;
            }
        return found;
    }

    static AutomationElement Find(AutomationElement parent, string name) => parent.FindFirst(TreeScope.Descendants, new PropertyCondition(AutomationElement.NameProperty, name)) ?? throw new InvalidOperationException("UIA要素がありません: " + name);

    static AutomationElement InputForLabel(AutomationElement main, string label)
    {
        var rect = Find(main, label).Current.BoundingRectangle;
        var edits = main.FindAll(TreeScope.Descendants, new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Edit)).Cast<AutomationElement>()
            .Where(e => Math.Abs(e.Current.BoundingRectangle.Top - rect.Top) < 3 && e.Current.BoundingRectangle.Left >= rect.Right).ToArray();
        if (edits.Length != 1) throw new InvalidOperationException("辞書の入力欄が一意ではありません: " + label);
        return edits[0];
    }

    static void ClickByMessage(nint hwnd, AutomationElement element)
    {
        var rect = element.Current.BoundingRectangle;
        if (rect.IsEmpty || element.Current.IsOffscreen) throw new InvalidOperationException("辞書の入力欄が画面にありません。");
        var point = new Point { X = (int)(rect.Left + rect.Width / 2), Y = (int)(rect.Top + rect.Height / 2) };
        if (!ScreenToClient(hwnd, ref point)) throw new InvalidOperationException("入力欄の座標変換に失敗しました。");
        var position = (nint)((point.Y & 0xffff) << 16 | point.X & 0xffff);
        SendMessage(hwnd, 0x201, 1, position);
        SendMessage(hwnd, 0x202, 0, position);
    }

    static string TextOf(AutomationElement edit) => ((TextPattern)edit.GetCurrentPattern(TextPattern.Pattern)).DocumentRange.GetText(-1).TrimEnd('\r', '\n');

    static void ReplaceText(nint hwnd, AutomationElement edit, string text)
    {
        ClickByMessage(hwnd, edit);
        ((TextPattern)edit.GetCurrentPattern(TextPattern.Pattern)).DocumentRange.Select();
        foreach (var character in text) SendMessage(hwnd, 0x102, character, 1);
        if (TextOf(edit) != text) throw new InvalidOperationException("入力欄へのメッセージ反映を確認できません。");
    }

    static void Enter(nint hwnd)
    {
        SendMessage(hwnd, 0x100, 0x0D, 0x001C0001);
        SendMessage(hwnd, 0x101, 0x0D, unchecked((nint)0xC01C0001));
    }

    static void Register(AutomationElement main, string planFile, string journalFile, string dictionaryFile)
    {
        var plan = JsonSerializer.Deserialize<Plan>(File.ReadAllText(planFile, Encoding.UTF8), JsonOptions) ?? throw new InvalidOperationException("登録計画が空です。");
        Validate(plan);
        var existing = ReadDictionary(dictionaryFile);
        // 競合は画面操作前に検出し、既存の発音を上書きしない。
        foreach (var entry in plan.Entries) ExistingReading(existing, entry);
        var directory = Path.GetDirectoryName(Path.GetFullPath(journalFile))!;
        Directory.CreateDirectory(directory);
        var backup = Path.Combine(directory, "dictionary-before.dic");
        if (File.Exists(backup) || File.Exists(journalFile)) throw new InvalidOperationException("登録台帳が既にあります。新しい実行先を指定してください。");
        File.WriteAllBytes(backup, ReadWithRetry(() => File.ReadAllBytes(dictionaryFile)));
        var initialLines = File.ReadAllLines(backup, Encoding.UTF8).Where(l => !string.IsNullOrWhiteSpace(l)).ToArray();
        var events = new List<object>();
        void Save() => File.WriteAllText(journalFile, JsonSerializer.Serialize(new { backup, method = "UIA + SendMessageTimeout", entries = events }, JsonOptions), new UTF8Encoding(false));
        Save();
        var button = Find(main, "user dictionary");
        var toggle = (TogglePattern)button.GetCurrentPattern(TogglePattern.Pattern);
        if (toggle.Current.ToggleState != ToggleState.On) toggle.Toggle();
        var hwnd = (nint)main.Current.NativeWindowHandle;
        if (IsIconic(hwnd))
        {
            ShowWindowAsync(hwnd, 9);
            var restoreWatch = Stopwatch.StartNew();
            while (IsIconic(hwnd) && restoreWatch.Elapsed.TotalSeconds < 3) Thread.Sleep(50);
            if (IsIconic(hwnd)) throw new InvalidOperationException("辞書登録のためのウィンドウ復元に失敗しました。");
            Thread.Sleep(150);
        }
        foreach (var entry in plan.Entries)
        {
            var watch = Stopwatch.StartNew();
            if (ExistingReading(existing, entry) != null)
            {
                events.Add(new { entry.Surface, entry.Reading, state = "already_registered", elapsedMs = watch.Elapsed.TotalMilliseconds }); Save(); continue;
            }
            try
            {
                var title = Find(main, "ユーザー辞書").Current.BoundingRectangle;
                var lists = main.FindAll(TreeScope.Descendants, new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.List)).Cast<AutomationElement>()
                    .Where(e => e.Current.BoundingRectangle.Left >= title.Left && e.Current.BoundingRectangle.Top >= title.Bottom).ToArray();
                if (lists.Length != 1) throw new InvalidOperationException("辞書リストが一意ではありません。");
                var grid = (GridPattern)lists[0].GetCurrentPattern(GridPattern.Pattern);
                var row = grid.GetItem(grid.Current.RowCount - 1, 0);
                ((SelectionItemPattern)row.GetCurrentPattern(SelectionItemPattern.Pattern)).Select();
                var surfaceEdit = InputForLabel(main, "表記:");
                var pronunciationEdit = InputForLabel(main, "発音:");
                if (TextOf(surfaceEdit).Length != 0) throw new InvalidOperationException("新規行の選択を確認できません。");
                ReplaceText(hwnd, surfaceEdit, entry.Surface);
                Enter(hwnd);
                ReplaceText(hwnd, pronunciationEdit, entry.Reading);
                Enter(hwnd);
                var wait = Stopwatch.StartNew();
                while (wait.Elapsed.TotalSeconds < 3)
                {
                    var now = ReadDictionary(dictionaryFile);
                    if (ExistingReading(now, entry) != null) break;
                    Thread.Sleep(30);
                }
                var after = ReadDictionary(dictionaryFile);
                if (ExistingReading(after, entry) == null) throw new InvalidOperationException("辞書ファイルで登録結果を確認できません。");
                if (existing.Any(pair => !after.TryGetValue(pair.Key, out var value) || value != pair.Value)) throw new InvalidOperationException("既存辞書項目の保持を確認できません。");
                existing = after;
                var storedSurface = after.ContainsKey(entry.Surface) ? entry.Surface : StorageSurface(entry.Surface);
                events.Add(new { entry.Surface, entry.Reading, storedSurface, state = "registered", elapsedMs = watch.Elapsed.TotalMilliseconds }); Save();
            }
            catch (Exception ex)
            {
                events.Add(new { entry.Surface, entry.Reading, state = "failed", error = ex.Message, elapsedMs = watch.Elapsed.TotalMilliseconds }); Save(); throw;
            }
        }
        var finalText = ReadWithRetry(() => File.ReadAllText(dictionaryFile, Encoding.UTF8));
        var finalLines = finalText.Split('\n').Select(l => l.TrimEnd('\r')).Where(l => !string.IsNullOrWhiteSpace(l)).ToArray();
        if (!finalLines.Take(initialLines.Length).SequenceEqual(initialLines)) throw new InvalidOperationException("既存辞書の順序・アクセントを含む保持確認に失敗しました。");
        File.WriteAllBytes(Path.Combine(directory, "dictionary-after.dic"), ReadWithRetry(() => File.ReadAllBytes(dictionaryFile)));
        Console.WriteLine(JsonSerializer.Serialize(new { registered = events.Count, journalFile }, JsonOptions));
    }
    [STAThread]
    static int Main(string[] args)
    {
        try
        {
            SetProcessDpiAwarenessContext(-4);
            if (args.Length == 1 && args[0] == "self-test")
            {
                if (StorageSurface("HTTPover①１～３") != "ＨＴＴＰｏｖｅｒ①１～３") throw new Exception("全角保存の試験に失敗しました。");
                var count = 0;
                if (ReadWithRetry(() => ++count < 3 ? throw new IOException() : "ok") != "ok" || count != 3) throw new Exception("一時ロック待機の試験に失敗しました。");
                if (ExistingReading(new() { ["ＨＴＴＰｏｖｅｒ"] = "オーバー" }, new("HTTPover", "オーバー")) != "オーバー") throw new Exception("保存済みの読戻し試験に失敗しました。");
                var rejected = false;
                try { ExistingReading(new() { ["ＨＴＴＰｏｖｅｒ"] = "ベツ" }, new("HTTPover", "オーバー")); }
                catch (InvalidOperationException) { rejected = true; }
                if (!rejected) throw new Exception("競合拒否の試験に失敗しました。");
                var temporary = Path.Combine(Path.GetTempPath(), "voisona-dictionary-" + Guid.NewGuid().ToString("N") + ".dic");
                var writer = new Thread(() => { Thread.Sleep(100); File.WriteAllText(temporary, "復元 [フクゲン] ACCENT=\"0\"\n", new UTF8Encoding(false)); });
                writer.Start();
                try
                {
                    if (ReadDictionary(temporary).GetValueOrDefault("復元") != "フクゲン") throw new Exception("一時消失からの復元試験に失敗しました。");
                }
                finally { writer.Join(); File.Delete(temporary); }
                Console.WriteLine("{\"tests\":5,\"passed\":true}"); return 0;
            }
            if (args.Length == 2 && args[0] == "validate")
            {
                Validate(JsonSerializer.Deserialize<Plan>(File.ReadAllText(args[1]), JsonOptions)!);
                Console.WriteLine("{\"valid\":true}"); return 0;
            }
            var processes = Process.GetProcessesByName("VoiSona Talk");
            if (processes.Length != 1) throw new InvalidOperationException("VoiSona Talkのプロセスが一意ではありません。");
            var root = AutomationElement.RootElement;
            var windows = root.FindAll(TreeScope.Children, new PropertyCondition(AutomationElement.ProcessIdProperty, processes[0].Id));
            if (args.Length == 4 && args[0] == "register")
            {
                var main = windows.Cast<AutomationElement>().Single(w => w.Current.Name.EndsWith("- VoiSona Talk Editor", StringComparison.Ordinal));
                Register(main, args[1], args[2], args[3]);
                return 0;
            }
            if (args.Length > 0 && args[0] == "dismiss")
            {
                foreach (AutomationElement w in windows)
                {
                    if (w.Current.NativeWindowHandle == 0) continue;
                    SendMessage(w.Current.NativeWindowHandle, 0x100, 0x1B, 0x001B0001);
                    SendMessage(w.Current.NativeWindowHandle, 0x101, 0x1B, unchecked((nint)0xC01B0001));
                }
                Console.WriteLine("{\"dismissed\":true}");
                return 0;
            }
            if (args.Length > 0 && args[0] == "enable-api")
            {
                var prefs = windows.Cast<AutomationElement>().Single(w => w.Current.Name == "環境設定");
                var check = prefs.FindAll(TreeScope.Descendants, new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.CheckBox)).Cast<AutomationElement>().Single();
                var toggle = (TogglePattern)check.GetCurrentPattern(TogglePattern.Pattern);
                if (toggle.Current.ToggleState != ToggleState.On) toggle.Toggle();
                Console.WriteLine("{\"enabled\":true}");
                return 0;
            }
            if (args.Length >= 2 && args[0] == "invoke")
            {
                var condition = new PropertyCondition(AutomationElement.NameProperty, args[1]);
                var element = windows.Cast<AutomationElement>().Select(w => w.FindFirst(TreeScope.Descendants, condition)).FirstOrDefault(e => e != null) ?? throw new InvalidOperationException("操作対象がありません: " + args[1]);
                if (element.TryGetCurrentPattern(InvokePattern.Pattern, out var invoke)) ((InvokePattern)invoke).Invoke();
                else if (element.TryGetCurrentPattern(ExpandCollapsePattern.Pattern, out var expand)) ((ExpandCollapsePattern)expand).Expand();
                else if (element.TryGetCurrentPattern(TogglePattern.Pattern, out var toggle)) ((TogglePattern)toggle).Toggle();
                else throw new InvalidOperationException("操作可能なUIAパターンがありません。");
                Console.WriteLine("{\"invoked\":true}");
                return 0;
            }
            var output = new List<object>();
            foreach (AutomationElement window in windows)
            {
                var all = window.FindAll(TreeScope.Subtree, Condition.TrueCondition);
                for (var i = 0; i < all.Count; i++)
                {
                    var element = all[i];
                    var current = element.Current;
                    if (current.IsPassword) continue;
                    if (window.Current.Name == "環境設定" && current.ControlType == ControlType.Edit) continue;
                    if (current.ControlType != ControlType.Edit && current.ControlType != ControlType.Button && current.ControlType != ControlType.CheckBox && current.ControlType != ControlType.Hyperlink && current.ControlType != ControlType.Window && current.ControlType != ControlType.MenuItem && current.ControlType != ControlType.List && current.ControlType != ControlType.ListItem && !current.Name.Contains("表記") && !current.Name.Contains("発音") && !current.Name.Contains("辞書")) continue;
                    var parent = TreeWalker.ControlViewWalker.GetParent(element);
                    var bounds = current.BoundingRectangle;
                    output.Add(new { Window = window.Current.Name, Name = current.Name, Id = current.AutomationId, Class = current.ClassName, Type = current.ControlType.ProgrammaticName, ParentName = parent?.Current.Name, ParentId = parent?.Current.AutomationId, NativeHandle = current.NativeWindowHandle, Enabled = current.IsEnabled, Bounds = new { bounds.X, bounds.Y, bounds.Width, bounds.Height }, Patterns = element.GetSupportedPatterns().Select(x => x.ProgrammaticName).ToArray() });
                }
            }
            Console.WriteLine(JsonSerializer.Serialize(output, new JsonSerializerOptions { WriteIndented = true }));
            return 0;
        }
        catch (Exception ex) { Console.Error.WriteLine(ex.Message); return 1; }
    }
}
