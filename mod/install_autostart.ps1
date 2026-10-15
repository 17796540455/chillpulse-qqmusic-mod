# ============================================================================
#  ChillPulse QQ音乐 Mod - 让桥接服务开机自动启动
#
#  安装： powershell -ExecutionPolicy Bypass -File install_autostart.ps1
#  卸载： powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Uninstall
#
#  优先注册「登录时启动」的计划任务（隐藏窗口 + 失败自动重启）；
#  如果没有权限注册计划任务，退回到「启动文件夹快捷方式」。
# ============================================================================
param(
    [string]$GameDir = "E:\steam\steam\steamapps\common\ChillPulse",
    [int]$Port = 38610,
    [int]$CacheMb = 1024,
    [string]$Quality = "128",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$TaskName = "ChillPulse-QQMusic-Bridge"
$ModDir = Join-Path $GameDir "QQMusicMod"
$Bridge = Join-Path $ModDir "qqbridge.py"
$StartBat = Join-Path $ModDir "start_bridge.bat"
$StartupDir = [Environment]::GetFolderPath("Startup")
$Shortcut = Join-Path $StartupDir "ChillPulse QQMusic Bridge.lnk"

function Info($m) { Write-Host "[autostart] $m" }

if ($Uninstall) {
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($t) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false; Info "removed scheduled task" }
    if (Test-Path -LiteralPath $Shortcut) { Remove-Item -LiteralPath $Shortcut -Force; Info "removed startup shortcut" }
    Info "autostart disabled"
    exit 0
}

if (-not (Test-Path -LiteralPath $Bridge)) { Write-Host "[autostart] ERROR: $Bridge not found"; exit 1 }

# ---- pick an interpreter -------------------------------------------------
$PyExe = $null
$PyArgs = @()
if (Test-Path -LiteralPath "C:\Windows\pyw.exe") {
    # pyw.exe is the windowless launcher: no console window ever appears
    $PyExe = "C:\Windows\pyw.exe"
    $PyArgs = @("-3")
} elseif (Test-Path -LiteralPath "C:\Windows\py.exe") {
    $PyExe = "C:\Windows\py.exe"
    $PyArgs = @("-3")
} else {
    $fallback = Join-Path $env:LOCALAPPDATA "..\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
    if (Test-Path -LiteralPath $fallback) { $PyExe = (Resolve-Path -LiteralPath $fallback).Path }
    elseif (Get-Command python.exe -ErrorAction SilentlyContinue) { $PyExe = (Get-Command python.exe).Source }
}
if (-not $PyExe) { Write-Host "[autostart] ERROR: no Python 3 interpreter found"; exit 1 }

$argList = @($PyArgs + @($Bridge, "--port", "$Port", "--game-dir", $GameDir,
                          "--cache-mb", "$CacheMb", "--quality", $Quality))
Info "interpreter : $PyExe"
Info "arguments   : $($argList -join ' ')"

$registered = $false
try {
    $action = New-ScheduledTaskAction -Execute $PyExe -Argument ($argList -join ' ') -WorkingDirectory $ModDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances IgnoreNew
    $settings.Hidden = $true
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Description "ChillPulse QQ Music bridge (127.0.0.1:$Port)" -Force | Out-Null
    $registered = $true
    Info "scheduled task '$TaskName' registered (runs hidden at logon, restarts on failure)"
} catch {
    Info "could not register a scheduled task ($($_.Exception.Message)); falling back to a Startup shortcut"
}

if (-not $registered) {
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($Shortcut)
    $lnk.TargetPath = $StartBat
    $lnk.WorkingDirectory = $ModDir
    $lnk.WindowStyle = 7            # minimised
    $lnk.Description = "ChillPulse QQ Music bridge"
    $lnk.Save()
    Info "startup shortcut created: $Shortcut"
}

# ---- start it right now so it works without a re-login -------------------
$listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Info "a bridge is already listening on $Port (pid $($listening.OwningProcess -join ','))"
} else {
    Info "starting the bridge now ..."
    Start-Process -FilePath $PyExe -ArgumentList ($argList -join ' ') -WorkingDirectory $ModDir -WindowStyle Hidden
    Start-Sleep -Seconds 8
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/status" -UseBasicParsing -TimeoutSec 15
        Info "bridge answers: $($r.Content)"
    } catch {
        Info "bridge did not answer yet - check $ModDir\qqbridge.log"
    }
}
Info "done."
