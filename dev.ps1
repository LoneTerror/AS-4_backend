python automated_run.py

if (Test-Path ".\venv\Scripts\Activate.ps1") {
    Write-Host ""
    Write-Host "Activating virtual environment..."
    . .\venv\Scripts\Activate.ps1
}