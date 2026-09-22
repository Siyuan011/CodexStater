param(
    [ValidateSet('Install','Status','Stop','Start','Remove')][string]$Action = 'Status',
    [string]$PythonPath,
    [string]$CodexRoot = (Join-Path $env:USERPROFILE '.codex')
)
$ErrorActionPreference = 'Stop'
$taskName = 'Codex-Local-Usage-Hourly'
switch ($Action) {
    'Install' {
        if (-not $PythonPath) {
            $PythonPath = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/pythonw.exe'
        }
        if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'Python runtime not found; specify -PythonPath.' }
        $runner = Join-Path $PSScriptRoot 'local-monitor.py'
        $arguments = '"{0}" --codex-root "{1}"' -f $runner, $CodexRoot
        $taskAction = New-ScheduledTaskAction -Execute $PythonPath -Argument $arguments -WorkingDirectory $PSScriptRoot
        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Hours 1)
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
        $principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $trigger -Settings $settings -Principal $principal -Description 'Local Codex quota and token sampling. No model turns. Every hour while signed in.' -Force | Out-Null
    }
    'Stop' { Disable-ScheduledTask -TaskName $taskName | Out-Null }
    'Start' { Enable-ScheduledTask -TaskName $taskName | Out-Null }
    'Remove' { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }
}
if ($Action -ne 'Remove') {
    $task = Get-ScheduledTask -TaskName $taskName
    $info = Get-ScheduledTaskInfo -TaskName $taskName
    [pscustomobject]@{Name=$task.TaskName;State=$task.State;LastRun=$info.LastRunTime;NextRun=$info.NextRunTime;LastResult=$info.LastTaskResult}
}
