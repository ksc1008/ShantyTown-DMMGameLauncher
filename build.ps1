# Single-file Windows exe build.
#
# Usage (from anywhere):
#     .\build.ps1
#
# Or right-click → "Run with PowerShell" from File Explorer.
#
# This is a thin wrapper around ``scripts\build_exe.py`` — it just
# anchors the working directory to the script's location, ensures
# dependencies are synced, runs the Python build orchestrator, and
# reports the resulting exe path / size.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $Root

Write-Host "==> uv sync" -ForegroundColor Cyan
uv sync
if ($LASTEXITCODE -ne 0) {
    Write-Host "uv sync failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "==> python scripts\build_exe.py" -ForegroundColor Cyan
uv run python scripts/build_exe.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "build_exe.py failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

$Exe = Join-Path $Root 'dist\shantytown.exe'
if (Test-Path $Exe) {
    $sizeMB = "{0:N1} MB" -f ((Get-Item $Exe).Length / 1MB)
    Write-Host ""
    Write-Host "Built: $Exe ($sizeMB)" -ForegroundColor Green
} else {
    Write-Host "Build did not produce dist\shantytown.exe" -ForegroundColor Red
    exit 1
}
