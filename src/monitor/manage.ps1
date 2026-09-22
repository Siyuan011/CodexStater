param(
 [ValidateSet('Install','Status','Pause','Resume','Remove','Ensure')][string]$Action='Status',
 [string]$PythonPath,
 [string]$ConfigPath
)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$name='Codex-Local-Usage-Hourly'
if ($Action -in @('Install','Ensure')) {
 $config=Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
 $minutes=[int]$config.monitor_interval_minutes
 if ($minutes -lt 5 -or $minutes -gt 1440) { throw '巡检间隔应为 5 至 1440 分钟。' }
 $pythonw=Join-Path (Split-Path $PythonPath) 'pythonw.exe'
 if (-not (Test-Path -LiteralPath $pythonw)) { throw '未找到 pythonw.exe，请安装完整 Python 或设置 STATER_PYTHON。' }
 $runner=Join-Path $root 'src/monitor/local_monitor.py'
 $args='"{0}" --config "{1}"' -f $runner,$ConfigPath
 $a=New-ScheduledTaskAction -Execute $pythonw -Argument $args -WorkingDirectory $root
 $existing=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
 $reuse=$false
 if ($Action -eq 'Ensure' -and $existing) {
  $reuse=($existing.Actions.Count -eq 1 -and $existing.Actions[0].Execute -eq $pythonw -and $existing.Actions[0].Arguments -eq $args -and $existing.Actions[0].WorkingDirectory -eq $root -and $existing.Triggers.Count -eq 1 -and $existing.Triggers[0].Repetition.Interval -eq [Xml.XmlConvert]::ToString((New-TimeSpan -Minutes $minutes)))
 }
 if (-not $reuse) {
 $t=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $minutes)
 $s=New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
 $p=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
 Register-ScheduledTask -TaskName $name -Action $a -Trigger $t -Settings $s -Principal $p -Description 'Local usage sampling without model turns' -Force | Out-Null
 Write-Host "已安装后台巡检，每 $minutes 分钟采样一次。"
 }
 if ($Action -eq 'Ensure') {
  Enable-ScheduledTask -TaskName $name | Out-Null
  if ((Get-ScheduledTask -TaskName $name).State -ne 'Running') { Start-ScheduledTask -TaskName $name }
  Write-Host "后台巡检已启用，已触发采样；每 $minutes 分钟自动运行。"
 }
}
if ($Action -eq 'Pause') { Disable-ScheduledTask -TaskName $name | Out-Null; Write-Host '已暂停巡检。' }
if ($Action -eq 'Resume') { Enable-ScheduledTask -TaskName $name | Out-Null; Write-Host '已恢复巡检。' }
if ($Action -eq 'Remove') { Unregister-ScheduledTask -TaskName $name -Confirm:$false; Write-Host '已卸载巡检，保留历史数据。'; return }
$task=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if (-not $task) { Write-Host '尚未安装后台巡检，请双击 scripts_cmd/install-monitor.cmd'; return }
$info=Get-ScheduledTaskInfo -TaskName $name
Write-Host "状态：$($task.State)"
Write-Host "上次运行：$($info.LastRunTime)；退出码：$($info.LastTaskResult)"
Write-Host "下次运行：$($info.NextRunTime)"
if (-not (Test-Path -LiteralPath $ConfigPath)) { return }
$c=Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$logDir=[Environment]::ExpandEnvironmentVariables([string]$c.logs_dir)
if (-not $logDir) { $logDir='logs' }
if ($logDir -eq '~') { $logDir=[Environment]::GetFolderPath('UserProfile') }
elseif ($logDir -match '^~[/\\]') { $logDir=Join-Path ([Environment]::GetFolderPath('UserProfile')) $logDir.Substring(2) }
if (-not [IO.Path]::IsPathRooted($logDir)) { $logDir=Join-Path $root $logDir }
$status=Join-Path $logDir 'local-monitor-status.json'
if (Test-Path -LiteralPath $status) { Get-Content -LiteralPath $status -Raw -Encoding UTF8 | Write-Host }
