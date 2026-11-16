Set-Location $PSScriptRoot
if (-not (Test-Path .\.venv\Scripts\python.exe)) { Write-Host "Run setup.ps1 first." -ForegroundColor Red; exit 1 }
& .\.venv\Scripts\python.exe -m pytest
