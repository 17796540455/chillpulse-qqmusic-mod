param([switch]$CopyLaunchOptions)
$ErrorActionPreference = 'Stop'
try {
    $Runtime = Join-Path $PSScriptRoot 'runtime'
    if (-not (Test-Path -LiteralPath (Join-Path $Runtime 'accounts.py'))) { $Runtime = $PSScriptRoot }
    if ($CopyLaunchOptions) {
        $options = Get-Content -LiteralPath (Join-Path $Runtime 'steam_launch_options.txt') -Raw -Encoding UTF8
        Set-Clipboard -Value $options.Trim()
        Write-Host '启动参数已复制。请粘贴到 Steam → ChillPulse → 属性 → 通用 → 启动选项。'
    } else {
        $PyExe = (Get-Content -LiteralPath (Join-Path $Runtime 'python_path.txt') -Raw -Encoding UTF8).Trim()
        Start-Process -FilePath $PyExe -ArgumentList ('"' + (Join-Path $Runtime 'accounts.py') + '"') -WindowStyle Hidden
    }
} catch {
    Write-Host '无法打开设置，请先运行 install.bat 完成安装。' -ForegroundColor Red
    Write-Host $_.Exception.Message
    Read-Host '按回车关闭'
    exit 1
}
