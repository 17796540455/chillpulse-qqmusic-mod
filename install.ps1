<#
    ChillPulse QQ Music Mod - one-click installer

    Does everything the manual steps used to need:
      1. finds your ChillPulse install (Steam libraries, or ask)
      2. checks Python 3 and ffmpeg, and says exactly how to fix them
      3. downloads the UndertaleModTool CLI (once, ~100 MB)
      4. backs up data.win and installs the patch
      5. starts the bridge once so you can sign in to QQ Music

    Usage:  powershell -ExecutionPolicy Bypass -File install.ps1
            powershell -ExecutionPolicy Bypass -File install.ps1 -Check      (dry run)
            powershell -ExecutionPolicy Bypass -File install.ps1 -GameDir "D:\...\ChillPulse"
#>
param(
    [string]$GameDir,
    [switch]$Check
)

$ErrorActionPreference = "Stop"
$Root    = $PSScriptRoot
$Bridge  = Join-Path $Root "bridge"
$Mod     = Join-Path $Root "mod"
$Tools   = Join-Path $Root "tools"
$UtmtDir = Join-Path $Tools "utmt-cli"
$UtmtExe = Join-Path $UtmtDir "UndertaleModCli.exe"
$UtmtZip = "https://github.com/UnderminersTeam/UndertaleModTool/releases/download/0.9.2.0/UTMT_CLI_v0.9.2.0-Windows.zip"
$Port    = 38612

function Step($n, $msg) { Write-Host ""; Write-Host "[$n] $msg" -ForegroundColor Cyan }
function Ok($msg)       { Write-Host "    OK   $msg" -ForegroundColor Green }
function Warn($msg)     { Write-Host "    WARN $msg" -ForegroundColor Yellow }
function Die($msg, $hint) {
    Write-Host "    FAIL $msg" -ForegroundColor Red
    if ($hint) { Write-Host "         $hint" -ForegroundColor Yellow }
    exit 1
}

Write-Host ""
Write-Host "  ChillPulse QQ Music Mod - installer" -ForegroundColor White
Write-Host "  ==================================" -ForegroundColor White

# ---------------------------------------------------------------- 1. game dir
Step 1 "Locating ChillPulse"
function Find-Game {
    $steam = (Get-ItemProperty "HKCU:\Software\Valve\Steam" -Name SteamPath -EA SilentlyContinue).SteamPath
    if (-not $steam) { return $null }
    $steam = $steam -replace '/', '\'
    $roots = @($steam)
    $lf = Join-Path $steam "steamapps\libraryfolders.vdf"
    if (Test-Path $lf) {
        foreach ($m in [regex]::Matches((Get-Content $lf -Raw), '"path"\s+"([^"]+)"')) {
            $roots += ($m.Groups[1].Value -replace '\\\\', '\')
        }
    }
    foreach ($r in $roots) {
        $p = Join-Path $r "steamapps\common\ChillPulse"
        if (Test-Path (Join-Path $p "ChillPulse.exe")) { return $p }
    }
    return $null
}
if (-not $GameDir) { $GameDir = Find-Game }
if (-not $GameDir) {
    if ($Check) { Warn "not found automatically (use -GameDir)" }
    else {
        Write-Host "    Could not find the game automatically."
        $GameDir = Read-Host "    Paste the ChillPulse folder path"
    }
}
if ($GameDir) {
    $GameDir = $GameDir.Trim('"').TrimEnd('\')
    if (-not (Test-Path (Join-Path $GameDir "ChillPulse.exe"))) {
        Die "no ChillPulse.exe in $GameDir" "Right-click the game in Steam -> Manage -> Browse local files"
    }
    Ok "game folder: $GameDir"
}

# ------------------------------------------------------------------ 2. python
Step 2 "Checking Python 3"
$PyExe = $null
foreach ($c in @("py", "python")) {
    try {
        $v = & $c -3 -V 2>&1
        if ($LASTEXITCODE -eq 0 -and "$v" -match "Python 3") { $PyExe = $c; Ok "$c -> $v"; break }
    } catch { }
}
if (-not $PyExe) {
    try { $v = & python -V 2>&1; if ("$v" -match "Python 3") { $PyExe = "python"; Ok "python -> $v" } } catch { }
}
if (-not $PyExe) {
    Die "Python 3 was not found" "Install it from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'"
}

# ------------------------------------------------------------------ 3. ffmpeg
Step 3 "Checking ffmpeg"
$Ffmpeg = Get-Command ffmpeg -EA SilentlyContinue
if ($Ffmpeg) { Ok "ffmpeg: $($Ffmpeg.Source)" }
elseif ($Check) { Warn "ffmpeg not found (winget install Gyan.FFmpeg)" }
else {
    Warn "ffmpeg not found - needed to transcode songs"
    $a = Read-Host "    Install it now with winget? (y/N)"
    if ($a -match '^[Yy]') { & winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements }
    if (-not (Get-Command ffmpeg -EA SilentlyContinue)) { Die "ffmpeg still missing" "winget install Gyan.FFmpeg, then reopen this window" }
    Ok "ffmpeg installed"
}

# --------------------------------------------------------------- 4. UTMT CLI
Step 4 "UndertaleModTool CLI"
if (Test-Path $UtmtExe) { Ok "already present" }
elseif ($Check) { Warn "not downloaded yet (~100 MB, fetched on first install)" }
else {
    New-Item -ItemType Directory -Force -Path $UtmtDir | Out-Null
    $zip = Join-Path $env:TEMP "UTMT_CLI.zip"
    Write-Host "    downloading (~100 MB) ..."
    try {
        Invoke-WebRequest -Uri $UtmtZip -OutFile $zip -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath $UtmtDir -Force
        Remove-Item $zip -Force -EA SilentlyContinue
    } catch { Die "download failed: $($_.Exception.Message)" "Grab it manually: $UtmtZip -> tools\utmt-cli\" }
    if (-not (Test-Path $UtmtExe)) {
        $found = Get-ChildItem $UtmtDir -Recurse -Filter "UndertaleModCli.exe" -EA SilentlyContinue | Select-Object -First 1
        if ($found) { $UtmtExe = $found.FullName } else { Die "UndertaleModCli.exe not in the archive" "Unpack it into tools\utmt-cli\" }
    }
    Ok "ready"
}

# ----------------------------------------------------------------- 5. patch
Step 5 "Patching the game"
if ($Check) { Warn "skipped in -Check mode" }
else {
    $dataWin = Join-Path $GameDir "data.win"
    $backup  = "$dataWin.qqmod-backup"
    if (-not (Test-Path $dataWin)) { Die "no data.win in the game folder" "Verify the game files in Steam first" }
    if (-not (Test-Path $backup)) {
        Copy-Item $dataWin $backup
        Ok "kept a pristine copy: data.win.qqmod-backup"
    } else { Ok "vanilla backup already exists" }

    $patched = Join-Path $Mod "data_patched.win"
    Remove-Item $patched -Force -EA SilentlyContinue
    Write-Host "    applying mod\apply_mod.csx ..."
    & $UtmtExe load $dataWin -s (Join-Path $Mod "apply_mod.csx") -o $patched 2>&1 |
        Select-String -Pattern "QQM:|Exception|error CS" | ForEach-Object { "      " + $_.Line }
    if (-not (Test-Path $patched)) { Die "the patcher produced no output" "See the message above; the game was probably updated" }

    Copy-Item $patched $dataWin -Force
    $hash = (Get-FileHash $dataWin -Algorithm SHA256).Hash.ToLower()
    Ok "installed (sha256 $($hash.Substring(0,16))...)"

    # keep the guard's expectation in sync so it can repair the patch later
    $guard = Join-Path $Mod "mod_guard.py"
    if (Test-Path $guard) {
        (Get-Content $guard -Raw) -replace 'PATCHED_SHA256 = "[0-9a-f]+"', "PATCHED_SHA256 = `"$hash`"" |
            Set-Content $guard -Encoding utf8
        Ok "mod_guard.py updated (auto-repairs after Steam verify/update)"
    }
}

# ----------------------------------------------------------------- 6. bridge
Step 6 "QQ Music sign-in"
$auth = Join-Path $Bridge "auth.json"
if ($Check) { Warn "skipped in -Check mode" }
else {
    if (Test-Path $auth) { Ok "auth.json already present" }
    else {
        Write-Host "    starting the bridge so you can sign in ..."
        Start-Process -FilePath "pyw" -ArgumentList "-3", (Join-Path $Bridge "qqbridge.py"),
            "--port", "$Port", "--game-dir", $GameDir -WindowStyle Hidden -EA SilentlyContinue
        Start-Sleep -Seconds 6
        Start-Process "http://127.0.0.1:$Port/login"
        Write-Host "    a browser page should have opened - scan it with mobile QQ," -ForegroundColor Yellow
        Write-Host "    or paste a cookie and press Enter here when done." -ForegroundColor Yellow
        Read-Host "    (Enter to continue)"
        if (Test-Path $auth) { Ok "signed in" } else { Warn "no auth.json yet - you can sign in later at http://127.0.0.1:$Port/login" }
    }
}

# ------------------------------------------------------------------ summary
Write-Host ""
Write-Host "  Done." -ForegroundColor Green
Write-Host ""
Write-Host "  To play:"
Write-Host "    1. start the bridge:  bridge\start_bridge.bat   (keep the window open)"
Write-Host "    2. start the game from Steam, press the ≡ button, pick the QQ Music tab"
Write-Host ""
if (Test-Path (Join-Path $Mod "launcher\launcher.py")) {
    Write-Host "  Optional: use the launcher in mod\launcher\ so the bridge starts and" -ForegroundColor DarkGray
    Write-Host "  stops with the game automatically." -ForegroundColor DarkGray
}
if (Test-Path (Join-Path $Mod "reinstall_mod.bat")) {
    Write-Host "  If Steam ever verifies the game files, run mod\reinstall_mod.bat." -ForegroundColor DarkGray
}
Write-Host ""
