param([string]$GameDir, [switch]$Check, [string]$Python, [string]$ToolDir)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$env:PYTHONUTF8 = '1'

function Find-Game {
    $steam = (Get-ItemProperty 'HKCU:\Software\Valve\Steam' -Name SteamPath -EA SilentlyContinue).SteamPath
    if (-not $steam) { return $null }
    $steam = $steam -replace '/', '\'
    $libraries = @($steam)
    $config = Join-Path $steam 'steamapps\libraryfolders.vdf'
    if (Test-Path -LiteralPath $config) {
        foreach ($match in [regex]::Matches((Get-Content -LiteralPath $config -Raw), '"path"\s+"([^"]+)"')) {
            $libraries += $match.Groups[1].Value.Replace('\\', '\')
        }
    }
    foreach ($library in $libraries) {
        $candidate = Join-Path $library 'steamapps\common\ChillPulse'
        if (Test-Path -LiteralPath (Join-Path $candidate 'ChillPulse.exe')) { return $candidate }
    }
}

function Find-Python {
    if ($Python) { return $Python }
    $candidates = @()
    try {
        $resolved = & py -3 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0) { $candidates += "$resolved" }
    } catch { }
    $command = Get-Command python -EA SilentlyContinue
    if ($command -and $command.Source -notmatch 'WindowsApps') { $candidates += $command.Source }
    foreach ($registry in @('HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore')) {
        foreach ($version in (Get-ChildItem $registry -EA SilentlyContinue)) {
            $key = Get-Item (Join-Path $version.PSPath 'InstallPath') -EA SilentlyContinue
            if ($key) { $candidates += Join-Path $key.GetValue('') 'python.exe' }
        }
    }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        & $candidate -c 'import sys, tkinter; assert sys.version_info >= (3, 9)' 2>$null
        if ($LASTEXITCODE -eq 0) { return $candidate }
    }
}

function Find-Ffmpeg {
    $command = Get-Command ffmpeg -EA SilentlyContinue
    if ($command) { return $command.Source }
    $link = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\ffmpeg.exe'
    if (Test-Path -LiteralPath $link) { return $link }
    foreach ($package in (Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages') -Directory -Filter 'Gyan.FFmpeg*' -EA SilentlyContinue)) {
        $found = Get-ChildItem $package.FullName -Recurse -Filter ffmpeg.exe -EA SilentlyContinue | Select-Object -First 1
        if ($found) { return $found.FullName }
    }
}

try {
    Write-Host 'ChillPulse · QQ / 网易云音乐 Mod 安装' -ForegroundColor Cyan
    if (-not $GameDir) { $GameDir = Find-Game }
    if (-not $GameDir) {
        if ($Check) { throw '未找到游戏。可用 -GameDir 指定包含 ChillPulse.exe 的目录。' }
        $GameDir = Read-Host '请粘贴游戏目录（Steam → 管理 → 浏览本地文件）'
    }
    $GameDir = [IO.Path]::GetFullPath($GameDir.Trim().Trim('"'))
    foreach ($name in @('ChillPulse.exe', 'data.win')) {
        if (-not (Test-Path -LiteralPath (Join-Path $GameDir $name))) { throw "游戏目录缺少 $name" }
    }
    Write-Host "游戏目录：$GameDir"
    $PyExe = Find-Python
    if (-not $PyExe) { throw '请先安装 python.org 的 Python 3.9 或更高版本，保留 tcl/tk 组件，然后重试。' }
    & $PyExe -c 'import sys, tkinter; assert sys.version_info >= (3, 9)'
    if ($LASTEXITCODE -ne 0) { throw 'Python 需要 3.9 或更高版本及 tkinter 组件。' }
    Write-Host "Python：$PyExe"
    $Ffmpeg = Find-Ffmpeg
    if (-not $Ffmpeg -and -not $Check) {
        if ((Read-Host '缺少 ffmpeg，是否通过 winget 安装？输入 Y 继续') -match '^[Yy]$') {
            & winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -ne 0) { throw 'ffmpeg 安装未成功，请完成安装后重试。' }
            $Ffmpeg = Find-Ffmpeg
        }
    }
    if (-not $Ffmpeg) { throw '未找到 ffmpeg。安装方式：winget install --id Gyan.FFmpeg -e' }
    Write-Host "ffmpeg：$Ffmpeg"
    if (-not $ToolDir) { $ToolDir = Join-Path $Root 'tools\utmt-cli' }
    $Utmt = Get-ChildItem $ToolDir -Recurse -Filter UndertaleModCli.exe -EA SilentlyContinue | Select-Object -First 1
    if ($Check) {
        if (-not $Utmt) { Write-Host '首次安装时将从官方 GitHub 下载补丁工具。' }
        Write-Host '环境检查完成；未安装、未修改游戏。' -ForegroundColor Green
        exit 0
    }
    if (-not $Utmt) {
        Write-Host '正在下载补丁工具（首次安装需要，可能需几分钟）……'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        New-Item -ItemType Directory -Force -Path $ToolDir | Out-Null
        $zip = Join-Path $ToolDir 'UTMT_CLI.zip'
        Invoke-WebRequest -Uri 'https://github.com/UnderminersTeam/UndertaleModTool/releases/download/0.9.2.0/UTMT_CLI_v0.9.2.0-Windows.zip' -OutFile $zip -UseBasicParsing
        Expand-Archive -LiteralPath $zip -DestinationPath $ToolDir -Force
        Remove-Item -LiteralPath $zip -Force
        $Utmt = Get-ChildItem $ToolDir -Recurse -Filter UndertaleModCli.exe | Select-Object -First 1
        if (-not $Utmt) { throw '工具下载不完整，请重新运行安装。' }
    }
    Write-Host '正在备份并生成 Mod，请不要关闭窗口……'
    $setupArguments = @((Join-Path $Root 'setup_mod.py'), '--game-dir', $GameDir, '--ffmpeg', $Ffmpeg, '--utmt', $Utmt.FullName)
    $Dotnet = Get-Command dotnet -EA SilentlyContinue
    $Dll = Join-Path $Utmt.DirectoryName 'UndertaleModCli.dll'
    if ($Dotnet -and (Test-Path -LiteralPath $Dll)) {
        $setupArguments[$setupArguments.Length - 1] = $Dll
        $setupArguments += @('--dotnet', $Dotnet.Source)
    }
    & $PyExe @setupArguments
    if ($LASTEXITCODE -ne 0) { throw '安装未完成，请按上方提示处理后重试。' }
    $options = Get-Content -LiteralPath (Join-Path $Root 'runtime\steam_launch_options.txt') -Raw -Encoding UTF8
    try { Set-Clipboard -Value $options.Trim(); Write-Host 'Steam 启动参数已复制到剪贴板。' -ForegroundColor Green }
    catch { Write-Host '请打开 runtime\steam_launch_options.txt，复制其中整行。' }
    Write-Host '接下来：Steam → ChillPulse → 属性 → 通用 → 启动选项，粘贴整行。'
    Write-Host '如有已有参数，请保留并放在 %command% 后。无需完全退出 Steam。'
    Write-Host '账号设置将打开。设置后，日常直接从 Steam 启动游戏即可。'
    & (Join-Path $Root 'accounts.ps1')
    exit 0
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
