# Build CampusGuard.exe on Windows 10/11 (64-bit) with Python 3.10-3.12.
#   powershell -ExecutionPolicy Bypass -File .\build_exe.ps1            (folder build: dist\CampusGuard\CampusGuard.exe)
#   powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -OneFile   (single dist\CampusGuard.exe)
# The script builds, then RUNS THE EXE'S SELF-TEST. Only a passing self-test means the build works.
param([switch]$OneFile)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .\.venv\Scripts\python.exe)) { Write-Host "Run setup.ps1 first." -ForegroundColor Red; exit 1 }
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install -r requirements.txt -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { Write-Host "Dependency install failed." -ForegroundColor Red; exit 1 }
if ($OneFile) { $env:CAMPUS_ONEFILE = "1" } else { Remove-Item Env:CAMPUS_ONEFILE -ErrorAction SilentlyContinue }
& $py -m PyInstaller CampusGuard.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { Write-Host "PyInstaller build failed." -ForegroundColor Red; exit 1 }
$exe = if ($OneFile) { ".\dist\CampusGuard.exe" } else { ".\dist\CampusGuard\CampusGuard.exe" }
if (-not (Test-Path $exe)) { Write-Host "Expected output not found: $exe" -ForegroundColor Red; exit 1 }
Write-Host "Running self-test of $exe ..."
$env:CAMPUS_SELFTEST_HOME = Join-Path $env:TEMP ("campusguard_selftest_" + [guid]::NewGuid())
& $exe --selftest
$code = $LASTEXITCODE
Remove-Item -Recurse -Force $env:CAMPUS_SELFTEST_HOME -ErrorAction SilentlyContinue
if ($code -ne 0) { Write-Host "SELF-TEST FAILED (exit $code). Do not distribute this build." -ForegroundColor Red; exit $code }
Write-Host "SELF-TEST PASSED. Built: $exe" -ForegroundColor Green
Write-Host "Zip the whole dist\CampusGuard folder (folder build) or send dist\CampusGuard.exe (one-file build)."
