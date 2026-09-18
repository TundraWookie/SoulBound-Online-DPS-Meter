$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name DpsMeter `
    --icon (Join-Path $PSScriptRoot "DpsMeter.ico") `
    (Join-Path $PSScriptRoot "DpsMeter.py")

Copy-Item -LiteralPath (Join-Path $PSScriptRoot "dist\DpsMeter.exe") `
    -Destination (Join-Path $PSScriptRoot "DpsMeter.exe") -Force

Write-Host "Built DpsMeter.exe with the Soulbound emblem."
