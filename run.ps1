# Start the server:  powershell -ExecutionPolicy Bypass -File .\run.ps1
Set-Location $PSScriptRoot
if (-not (Test-Path .\.venv\Scripts\python.exe)) { Write-Host "Run setup.ps1 first." -ForegroundColor Red; exit 1 }
Write-Host "Starting on http://127.0.0.1:8000  (Ctrl+C to stop). First start prints the admin password."
Start-Job { Start-Sleep 4; Start-Process "http://127.0.0.1:8000" } | Out-Null
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
