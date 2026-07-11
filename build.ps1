# Windows build wrapper.
#
# Usage (from anywhere):
#     .\build.ps1                     # both exes (main + helper)
#     .\build.ps1 --target main       # main app only (browser-only install)
#     .\build.ps1 --target helper     # webview login helper only
#
# Or right-click -> "Run with PowerShell" from File Explorer.
#
# Thin wrapper around ``scripts\build_exe.py``: anchors the working
# directory, syncs dependencies, forwards any args to the Python build
# orchestrator, and reports the resulting exe(s) / size(s).
#
# Produces TWO single-file exes in ``dist\``:
#   shantytown.exe      - the app (QtWebEngine excluded; fast startup)
#   __loginhelper.exe    - webview login engine (spawned on demand)
# Ship them together in one folder. shantytown.exe alone = browser-only.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $Root

Write-Host "==> uv sync" -ForegroundColor Cyan
uv sync
if ($LASTEXITCODE -ne 0) {
    Write-Host "uv sync failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "==> python scripts\build_exe.py $args" -ForegroundColor Cyan
uv run python scripts/build_exe.py @args
if ($LASTEXITCODE -ne 0) {
    Write-Host "build_exe.py failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

$Exes = Get-ChildItem -Path (Join-Path $Root 'dist') -File -Filter '*.exe' -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -in @('shantytown.exe', '__loginhelper.exe') }
if ($Exes) {
    Write-Host ""
    foreach ($e in $Exes) {
        $sizeMB = "{0:N0} MB" -f ($e.Length / 1MB)
        Write-Host "Built: $($e.FullName) ($sizeMB)" -ForegroundColor Green
    }
} else {
    Write-Host "Build did not produce dist\shantytown.exe or __loginhelper.exe" -ForegroundColor Red
    exit 1
}
