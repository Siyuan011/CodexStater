[CmdletBinding()]
param(
    [ValidateSet('launch', 'stop', 'export')]
    [string]$Action = 'launch',
    [string]$Config = '',
    [string]$CodexRoot = '',
    [switch]$NoBrowser,
    [switch]$Check,
    [switch]$NonInteractive
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$utf8 = New-Object System.Text.UTF8Encoding($false)
$userDirectory = [Environment]::GetFolderPath('UserProfile')

function Resolve-LocalPath([string]$Value, [string]$BaseDirectory) {
    $expanded = [Environment]::ExpandEnvironmentVariables($Value.Trim())
    if ($expanded -eq '~') { $expanded = $userDirectory }
    elseif ($expanded -match '^~[/\\]') { $expanded = Join-Path $userDirectory $expanded.Substring(2) }
    if (-not [IO.Path]::IsPathRooted($expanded)) { $expanded = Join-Path $BaseDirectory $expanded }
    return [IO.Path]::GetFullPath($expanded)
}

function Test-Python([string]$Executable, [string]$Prefix = '') {
    # Probe executables with a timeout; Windows Store aliases are not interpreters.
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { return $null }
    if ($Executable -match '[\\/]Microsoft[\\/]WindowsApps[\\/]') { return $null }
    $probe = New-Object System.Diagnostics.Process
    $probe.StartInfo.FileName = $Executable
    $probe.StartInfo.Arguments = $Prefix + ' -X utf8 -c "import sys; print(sys.executable); sys.exit(0 if sys.version_info >= (3, 9) else 1)"'
    $probe.StartInfo.UseShellExecute = $false
    $probe.StartInfo.CreateNoWindow = $true
    $probe.StartInfo.RedirectStandardOutput = $true
    $probe.StartInfo.RedirectStandardError = $true
    $probe.StartInfo.StandardOutputEncoding = [Text.Encoding]::UTF8
    $probe.StartInfo.StandardErrorEncoding = [Text.Encoding]::UTF8
    try {
        if (-not $probe.Start()) { return $null }
        $outputTask = $probe.StandardOutput.ReadToEndAsync()
        $errorTask = $probe.StandardError.ReadToEndAsync()
        if (-not $probe.WaitForExit(8000)) { $probe.Kill(); return $null }
        $result = $outputTask.GetAwaiter().GetResult().Trim()
        $null = $errorTask.GetAwaiter().GetResult()
        if ($probe.ExitCode -eq 0 -and (Test-Path -LiteralPath $result -PathType Leaf)) { return $result }
    }
    catch { return $null }
    finally { $probe.Dispose() }
    return $null
}

function Find-Python {
    if (-not [string]::IsNullOrWhiteSpace($env:STATER_PYTHON)) {
        $override = Resolve-LocalPath $env:STATER_PYTHON $projectRoot
        $found = Test-Python $override
        if ($found) { return $found }
        throw 'STATER_PYTHON 指定的解释器不可用。请指定 Python 3.9+ 的 python.exe，或清除此环境变量后重试。'
    }
    foreach ($name in @('py.exe', 'python.exe', 'python3.exe')) {
        foreach ($command in @(Get-Command $name -CommandType Application -All -ErrorAction SilentlyContinue)) {
            $prefix = ''
            if ($name -eq 'py.exe') { $prefix = '-3' }
            $found = Test-Python $command.Source $prefix
            if ($found) { return $found }
        }
    }
    $patterns = @(
        (Join-Path $userDirectory '.cache\codex-runtimes\*\dependencies\python\python.exe'),
        (Join-Path $userDirectory '.cache\codex-runtimes\*\python\python.exe')
    )
    if ($env:LOCALAPPDATA) { $patterns += Join-Path $env:LOCALAPPDATA 'Programs\Python\Python*\python.exe' }
    if ($env:ProgramFiles) { $patterns += Join-Path $env:ProgramFiles 'Python*\python.exe' }
    foreach ($pattern in $patterns) {
        foreach ($candidate in @(Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)) {
            $found = Test-Python $candidate.FullName
            if ($found) { return $found }
        }
    }
    throw '没有找到 Python 3.9+。请安装 Python 并勾选 Add python.exe to PATH，或用 STATER_PYTHON 指定已有解释器的完整路径。'
}

function Save-LocalConfig {
    $directory = Split-Path -Parent $configPath
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        throw "配置文件的父目录不存在：$directory"
    }
    [IO.File]::WriteAllText($configPath, ($settings | ConvertTo-Json -Depth 20), $utf8)
}

function Find-CodexRoot {
    if (-not [string]::IsNullOrWhiteSpace($CodexRoot)) {
        $explicit = Resolve-LocalPath $CodexRoot $projectRoot
        if ($Action -eq 'stop' -or (Test-Path -LiteralPath $explicit -PathType Container)) { return $explicit }
        throw "指定的 Codex 数据目录不存在：$explicit"
    }
    if ($Action -eq 'stop' -and (Test-Path -LiteralPath $launcherStatePath -PathType Leaf)) {
        $lastLaunch = Get-Content -LiteralPath $launcherStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($lastLaunch.PSObject.Properties['codex_root'] -and $lastLaunch.codex_root) {
            return [string]$lastLaunch.codex_root
        }
    }
    $candidates = @()
    if ($settings.PSObject.Properties['codex_root'] -and -not [string]::IsNullOrWhiteSpace([string]$settings.codex_root)) {
        $configured = Resolve-LocalPath ([string]$settings.codex_root) (Split-Path -Parent $configPath)
        # Stopping must still work if the original data directory has moved.
        if ($Action -eq 'stop' -or (Test-Path -LiteralPath $configured -PathType Container)) { return $configured }
        Write-Warning "配置中的数据目录已不存在，将自动检测本机目录：$configured"
    }
    if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
        $candidates += Resolve-LocalPath $env:CODEX_HOME $projectRoot
    }
    $candidates += Join-Path $userDirectory '.codex'
    foreach ($candidate in $candidates) {
        if ($Action -eq 'stop' -or (Test-Path -LiteralPath $candidate -PathType Container)) { return $candidate }
    }
    if ($Check -or $NonInteractive) {
        throw '未找到 Codex 数据目录。请先在本机使用 Codex，或设置 CODEX_HOME、config.json 的 codex_root，或传入 -CodexRoot。'
    }
    Add-Type -AssemblyName System.Windows.Forms
    $picker = New-Object System.Windows.Forms.FolderBrowserDialog
    try {
        $picker.Description = '未找到 Codex 数据目录。请选择保存 sessions 日志的 .codex 文件夹。'
        $picker.ShowNewFolderButton = $false
        $picker.SelectedPath = $userDirectory
        if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
            throw '已取消选择 Codex 数据目录，未启动服务。'
        }
        $selected = $picker.SelectedPath
    }
    finally { $picker.Dispose() }
    $settings | Add-Member -NotePropertyName codex_root -NotePropertyValue $selected -Force
    Save-LocalConfig
    return $selected
}

try {
    if ([string]::IsNullOrWhiteSpace($Config)) { $Config = 'config.json' }
    $configPath = Resolve-LocalPath $Config $projectRoot
    $stateHasher = [Security.Cryptography.SHA256]::Create()
    try { $configKey = [BitConverter]::ToString($stateHasher.ComputeHash($utf8.GetBytes($configPath.ToLowerInvariant()))).Replace('-', '').Substring(0, 24) }
    finally { $stateHasher.Dispose() }
    $launcherStatePath = Join-Path $projectRoot ('.cache\launcher-state-' + $configKey + '.json')
    $configExists = Test-Path -LiteralPath $configPath -PathType Leaf
    if ($configExists) {
        $settings = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    else {
        $settings = Get-Content -LiteralPath (Join-Path $projectRoot 'config.example.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    if ($null -eq $settings -or $settings -isnot [pscustomobject]) { throw '配置文件必须是 JSON 对象。' }
    $pythonPath = Find-Python
    $dataRoot = Find-CodexRoot
    if ($Check) {
        [ordered]@{ python = $pythonPath; codex_root = $dataRoot; config = $configPath; action = $Action } | ConvertTo-Json
        exit 0
    }
    if (-not $configExists -and -not (Test-Path -LiteralPath $configPath -PathType Leaf)) { Save-LocalConfig }
    $appArguments = @((Join-Path $projectRoot 'app.py'), $Action, '--config', $configPath, '--codex-root', $dataRoot)
    if ($Action -eq 'launch' -and $NoBrowser) { $appArguments += '--no-browser' }
    if ($Action -eq 'export') {
        $reportPath = Join-Path $projectRoot '最新用量报告.html'
        $appArguments += @('--output', $reportPath)
    }
    Write-Host "Python：$pythonPath"
    Write-Host "Codex 数据目录：$dataRoot"
    Push-Location -LiteralPath $projectRoot
    try {
        & $pythonPath @appArguments
        $appExitCode = $LASTEXITCODE
    }
    finally { Pop-Location }
    if ($appExitCode -ne 0) { throw "执行失败（退出码 $appExitCode），请查看上方信息。" }
    if ($Action -eq 'launch') {
        $null = [IO.Directory]::CreateDirectory((Split-Path -Parent $launcherStatePath))
        [IO.File]::WriteAllText($launcherStatePath, (@{ codex_root = $dataRoot } | ConvertTo-Json), $utf8)
    }
    if ($Action -eq 'export' -and -not $NoBrowser) { Start-Process -FilePath $reportPath }
    exit 0
}
catch {
    $errorText = $_.Exception.Message
    try {
        $logDirectory = Join-Path $projectRoot '.cache'
        $null = [IO.Directory]::CreateDirectory($logDirectory)
        [IO.File]::WriteAllText((Join-Path $logDirectory 'launcher-error.txt'), $errorText, $utf8)
    }
    catch { }
    Write-Host ("启动入口错误：" + $errorText) -ForegroundColor Red
    exit 1
}
