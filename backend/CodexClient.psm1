function Write-CodexLlmLog { param($Prompt,$Output,$Model,$Status,$DurationSeconds,$Error) }
function Resolve-CodexExecutable {
    param([string]$CodexPath = 'codex.exe')
    $isDefault = $CodexPath -in 'codex', 'codex.exe'
    if ($isDefault) {
        # WindowsApps配下の実体はGet-Commandで見えても、通常アプリからの起動が
        # アクセス拒否になることがある。先にユーザー領域の実行可能コピーを探す。
        $candidatePaths = [Collections.Generic.List[string]]::new()
        if ($env:USERPROFILE) {
            $candidatePaths.Add((Join-Path $env:USERPROFILE '.codex/.sandbox-bin/codex.exe'))
            $candidatePaths.Add((Join-Path $env:USERPROFILE '.codex/plugins/.plugin-appserver/codex.exe'))
        }
        if ($env:LOCALAPPDATA) {
            $binRoot = Join-Path $env:LOCALAPPDATA 'OpenAI/Codex/bin'
            Get-ChildItem -LiteralPath $binRoot -Directory -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTimeUtc -Descending |
                ForEach-Object { $candidatePaths.Add((Join-Path $_.FullName 'codex.exe')) }
        }
        foreach ($candidate in $candidatePaths) {
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
        }
    }
    $command = Get-Command $CodexPath -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command -and [IO.Path]::GetExtension($command.Source) -eq '.exe' -and
        (!$isDefault -or $command.Source -notlike '*\WindowsApps\OpenAI.Codex_*')) {
        return $command.Source
    }
    throw 'Codex CLIの実行ファイルが見つかりません。CODEX_PATHにcodex.exeのパスを設定してください。'
}

function Invoke-CodexReply {
    param([object[]]$History, [string]$CodexPath = 'codex.exe', [string]$Model,
        [ValidateRange(1,3600)][int]$TimeoutSeconds = 180, [string]$Prompt)
    $timer = [Diagnostics.Stopwatch]::StartNew()
    if (!$Prompt) { throw '検証用プロンプトを指定してください。' }
    try { $executable = Resolve-CodexExecutable $CodexPath }
    catch {
        Write-CodexLlmLog -Prompt $Prompt -Output '' -Model $Model -Status 'failed' -DurationSeconds $timer.Elapsed.TotalSeconds -Error $_.Exception.Message
        throw
    }    $directory = Join-Path ([IO.Path]::GetTempPath()) ('ReadingRepair-' + [guid]::NewGuid().ToString('N'))
    $null = [IO.Directory]::CreateDirectory($directory)
    $output = Join-Path $directory 'reply.txt'
    $process = [Diagnostics.Process]::new()
    $started = $false
    try {
        $start = [Diagnostics.ProcessStartInfo]::new()
        $start.FileName = $executable
        $start.WorkingDirectory = $directory
        $start.UseShellExecute = $false
        $start.CreateNoWindow = $true
        $start.RedirectStandardInput = $true
        $start.RedirectStandardOutput = $true
        $start.RedirectStandardError = $true
        $start.StandardInputEncoding = [Text.UTF8Encoding]::new($false)
        $start.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
        $start.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
        foreach ($key in @($start.Environment.Keys)) {
            if ($key -like 'VOISONA_*') { $null = $start.Environment.Remove($key) }
        }
        $start.Environment['READINGREPAIR_INTERNAL_CODEX']='1'
        foreach ($argument in @('exec', '--ignore-user-config', '--ephemeral', '--skip-git-repo-check',
            '--sandbox', 'read-only', '--color', 'never', '-c', 'approval_policy="never"',
            '-c', 'features.shell_tool=false', '-c', 'features.unified_exec=false',
            '-c', 'web_search="disabled"', '-c', 'project_doc_max_bytes=0',
            '--output-last-message', $output)) { $start.ArgumentList.Add($argument) }
        if ($Model) { $start.ArgumentList.Add('--model'); $start.ArgumentList.Add($Model) }
        $start.ArgumentList.Add('-')
        $process.StartInfo = $start
        $null = $process.Start()
        $started = $true
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        # 実行ファイル解決からの全所要時間を記録する。
        $write = $process.StandardInput.WriteAsync($prompt)
        while (!$write.IsCompleted -and $timer.Elapsed.TotalSeconds -lt $TimeoutSeconds) { Start-Sleep -Milliseconds 100 }
        if (!$write.IsCompleted) { throw 'Codex CLIへの入力がタイムアウトしました。' }
        $null = $write.GetAwaiter().GetResult()
        $process.StandardInput.Close()
        while (!$process.WaitForExit(200)) {
            if ($timer.Elapsed.TotalSeconds -ge $TimeoutSeconds) { throw 'Codex CLIの返答待機がタイムアウトしました。' }
        }
        $null = $stdout.GetAwaiter().GetResult()
        $null = $stderr.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0) {
            throw "Codex CLIが終了コード $($process.ExitCode) で失敗しました。codex login status、通信状態、モデル設定を確認してください。"
        }
        if (!(Test-Path -LiteralPath $output)) { throw 'Codex CLIから返答ファイルが出力されませんでした。' }
        $reply = [IO.File]::ReadAllText($output, [Text.Encoding]::UTF8).Trim()
        if ([string]::IsNullOrWhiteSpace($reply)) { throw 'Codex CLIの返答が空です。' }
        Write-CodexLlmLog -Prompt $Prompt -Output $reply -Model $Model -Status 'success' -DurationSeconds $timer.Elapsed.TotalSeconds -Error ''
        return $reply
    } catch {
        Write-CodexLlmLog -Prompt $Prompt -Output '' -Model $Model -Status 'failed' -DurationSeconds $timer.Elapsed.TotalSeconds -Error $_.Exception.Message
        throw
    } finally {
        if ($started -and !$process.HasExited) { $process.Kill($true); $process.WaitForExit() }
        $process.Dispose()
        # この呼び出しで生成した一時フォルダーだけを削除する。
        $resolved = [IO.Path]::GetFullPath($directory)
        $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
        if ($resolved.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and
            [IO.Path]::GetFileName($resolved) -match '^ReadingRepair-[0-9a-f]{32}$') {
            Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

