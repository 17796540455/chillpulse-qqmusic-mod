# ============================================================================
#  ChillPulse QQ Music mod - installer / updater
#
#  Usage:  powershell -ExecutionPolicy Bypass -File install_mod.ps1
#          powershell -ExecutionPolicy Bypass -File install_mod.ps1 -Uninstall
#
#  - backs up the pristine data.win once (data.win.qqmod-backup)
#  - installs the patched data.win
#  - installs the bridge service into <game>\QQMusicMod\
# ============================================================================
param(
    [string]$GameDir = "E:\steam\steam\steamapps\common\ChillPulse",
    [string]$ModRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [switch]$Uninstall,
    [switch]$SkipDataWin
)

$ErrorActionPreference = "Stop"

function Info($m) { Write-Host "[qqmod] $m" }
function Fail($m) { Write-Host "[qqmod] ERROR: $m" -ForegroundColor Red; exit 1 }

if (-not (Test-Path -LiteralPath $GameDir)) { Fail "game folder not found: $GameDir" }
$dataWin   = Join-Path $GameDir "data.win"
$backup    = Join-Path $GameDir "data.win.qqmod-backup"
$modDir    = Join-Path $GameDir "QQMusicMod"
$patched   = Join-Path $ModRoot "mods\work\data_patched.win"

if ($Uninstall) {
    if (Test-Path -LiteralPath $backup) {
        Copy-Item -LiteralPath $backup -Destination $dataWin -Force
        Info "restored original data.win from backup"
    } else {
        Info "no backup found - nothing to restore"
    }
    if (Test-Path -LiteralPath $modDir) {
        Remove-Item -LiteralPath $modDir -Recurse -Force
        Info "removed $modDir"
    }
    Info "uninstalled"
    exit 0
}

# --- 1. back up the original data.win exactly once -------------------------
if (-not (Test-Path -LiteralPath $backup)) {
    Copy-Item -LiteralPath $dataWin -Destination $backup -Force
    Info "backed up original data.win -> data.win.qqmod-backup"
} else {
    Info "backup already exists, keeping it untouched"
}

# --- 2. install the patched data.win --------------------------------------
if ($SkipDataWin) {
    Info "skipping data.win install (-SkipDataWin)"
} else {
    if (-not (Test-Path -LiteralPath $patched)) { Fail "patched data.win not found: $patched" }
    Copy-Item -LiteralPath $patched -Destination $dataWin -Force
    $h = (Get-FileHash -LiteralPath $dataWin -Algorithm SHA256).Hash
    Info "installed patched data.win (sha256 $($h.Substring(0,16))...)"
}

# --- 3. the bridge + toolkit live OUTSIDE the Steam library ----------------
# Only data.win and qqmusic_cache have to sit inside the game folder.  Keeping
# everything else out means a game reinstall, a library move or a cleanup pass
# cannot touch it (Steam only ever restores files from its own manifest).
$bridgeHome = "E:\ChillPulseQQMod"
if (-not (Test-Path -LiteralPath (Join-Path $bridgeHome "qqbridge.py"))) {
    New-Item -ItemType Directory -Force -Path $bridgeHome | Out-Null
    $bridgeSrc = Join-Path $ModRoot "mods\install\bridge"
    if (Test-Path -LiteralPath $bridgeSrc) {
        Copy-Item -Path (Join-Path $bridgeSrc "*") -Destination $bridgeHome -Recurse -Force
        Info "seeded the bridge toolkit into $bridgeHome"
    }
}
New-Item -ItemType Directory -Force -Path $modDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $GameDir "qqmusic_cache") | Out-Null
# a forwarder in the game folder so launch options / shortcuts pointing at the
# old location keep working
$stub = Join-Path $ModRoot "mods\install\bridge_launch_stub.vbs"
if (Test-Path -LiteralPath $stub) {
    Copy-Item -LiteralPath $stub -Destination (Join-Path $modDir "bridge_launch.vbs") -Force
}
foreach ($extra in @("qqbridge.py", "qqmusic.py", "README.md", "qqbridge.log")) {
    Remove-Item -LiteralPath (Join-Path $modDir $extra) -Force -ErrorAction SilentlyContinue
}

Info "done. Bridge + tools live in $bridgeHome"
Info "      if Steam ever restores data.win, run $bridgeHome\fix_mod.bat"
