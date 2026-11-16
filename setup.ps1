# One-time setup (Windows PowerShell). Run:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
# Add -WithML to also install PyTorch + Ultralytics (large download, optional).
param([switch]$WithML)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = $null
foreach ($c in @("py -3.12", "py -3.11", "py -3.10", "python")) {
    try {
        $v = & cmd /c "$c --version 2>&1"
        if ($v -match "Python 3\.(10|11|12)\.") { $py = $c; break }
    } catch {}
}
if (-not $py) {
    Write-Host "Python 3.10, 3.11 or 3.12 was not found." -ForegroundColor Red
    Write-Host "Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then re-run." ; exit 1
}
Write-Host "Using: $py"
if (-not (Test-Path .venv)) { & cmd /c "$py -m venv .venv" }
$vpy = ".\.venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip
& $vpy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Host "Dependency install failed. See README 'Troubleshooting'." -ForegroundColor Red; exit 1 }
if ($WithML) {
    & $vpy -m pip install -r requirements-ml.txt
    if ($LASTEXITCODE -ne 0) { Write-Host "Optional ML install failed; the app still works with the OpenCV fallback." -ForegroundColor Yellow }
}
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env" }
foreach ($d in @("data", "data\videos", "data\evidence", "data\backups", "models", "reference_images")) { New-Item -ItemType Directory -Force $d | Out-Null }
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "NOTE: ffmpeg not found on PATH. The app works, but AVI/MOV browser preview and evidence clips need it." -ForegroundColor Yellow
    Write-Host "      Install with:  winget install Gyan.FFmpeg   (then open a NEW terminal)"
}
Write-Host "Setup complete. Start the app with:  powershell -ExecutionPolicy Bypass -File .\run.ps1" -ForegroundColor Green
