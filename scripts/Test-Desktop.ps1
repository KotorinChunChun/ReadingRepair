#requires -Version 7.0
param([string]$Executable=(Join-Path $PSScriptRoot '../Desktop/bin/Debug/net10.0-windows/ReadingRepair.exe'),[string]$Output=(Join-Path $PSScriptRoot '../dev/history/v0.0.2/logs/desktop'))
$ErrorActionPreference='Stop'
$exe=[IO.Path]::GetFullPath($Executable);$out=[IO.Path]::GetFullPath($Output)
[IO.Directory]::CreateDirectory($out)|Out-Null
$id='reading-repair-test-'+[guid]::NewGuid().ToString('N')
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$pipeName='KotorinToys.'+$sid+'.'+$id
function Request($value){
    $pipe=[IO.Pipes.NamedPipeClientStream]::new('.',$pipeName,[IO.Pipes.PipeDirection]::InOut,[IO.Pipes.PipeOptions]::CurrentUserOnly)
    try {
        $pipe.Connect(2000)
        $writer=[IO.StreamWriter]::new($pipe,[Text.UTF8Encoding]::new($false),1024,$true);$writer.AutoFlush=$true
        $reader=[IO.StreamReader]::new($pipe,[Text.Encoding]::UTF8,$true,1024,$true)
        try {$writer.WriteLine(($value|ConvertTo-Json -Compress));return ($reader.ReadLineAsync().WaitAsync([TimeSpan]::FromSeconds(3)).GetAwaiter().GetResult()|ConvertFrom-Json)}
        finally {$writer.Dispose();$reader.Dispose()}
    } finally {$pipe.Dispose()}
}
$settings=Join-Path $out 'settings.json'
$args=@('--instance-id',$id,'--settings',$settings,'--startup')
$process=Start-Process -FilePath $exe -ArgumentList ($args|ForEach-Object {'"'+$_+'"'}) -PassThru -WindowStyle Hidden
try {
    $deadline=[DateTime]::UtcNow.AddSeconds(30);$status=$null
    while([DateTime]::UtcNow -lt $deadline){
        try {$status=Request @{command='status';expectedPid=$process.Id};if($status.ready){break}}catch{}
        Start-Sleep -Milliseconds 200
    }
    if(!$status -or !$status.ready -or $status.pid -ne $process.Id){throw '管理準備を確認できません。'}
    $process.Refresh();$hidden=($process.MainWindowHandle -eq 0)
    if(!$hidden){throw 'startupが画面を表示しました。'}
    $wrong=Request @{command='stop';expectedPid=0}
    if($wrong.result -ne 'refused'){throw '誤PIDの停止を拒否しませんでした。'}
    $shown=Request @{command='show';expectedPid=$process.Id}
    if($shown.result -ne 'completed'){throw '表示要求に失敗しました。'}
    Start-Sleep -Milliseconds 300
    $process.Refresh();if($process.MainWindowHandle -eq 0){throw 'show後に画面がありません。'}
    $duplicate=Start-Process -FilePath $exe -ArgumentList ($args|ForEach-Object {'"'+$_+'"'}) -PassThru -WindowStyle Hidden
    if(!$duplicate.WaitForExit(5000)){throw '重複起動が終了しません。'}
    $still=Request @{command='status';expectedPid=$process.Id}
    if($still.pid -ne $process.Id){throw '既存PIDを保持しませんでした。'}
    $stopped=Request @{command='stop';expectedPid=$process.Id}
    if($stopped.result -ne 'accepted' -or !$process.WaitForExit(5000)){throw '正常停止を確認できません。'}
    @{protocol=$status.protocolVersion;pid=$process.Id;hidden=$hidden;wrong_pid=$wrong.result;show=$shown.result;duplicate_preserved=$true;stop=$stopped.result;version=$status.version}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $out 'management.json') -Encoding utf8
} finally {
    if(!$process.HasExited){$process.CloseMainWindow()|Out-Null}
}
$smoke=Join-Path $out 'smoke.json'
$smokeArgs=@('--instance-id',$id,'--settings',$settings,'--smoke-report',$smoke)
$ui=Start-Process -FilePath $exe -ArgumentList ($smokeArgs|ForEach-Object {'"'+$_+'"'}) -PassThru -WindowStyle Hidden
if(!$ui.WaitForExit(30000) -or $ui.ExitCode -ne 0){throw 'WPF表示・ボタン説明の検査に失敗しました。'}
Get-Content -LiteralPath (Join-Path $out 'management.json');Get-Content -LiteralPath $smoke
