$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot\backend"

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Write-Host "Created backend\.env from backend\.env.example."
}

if (-not (Test-Path ".venv")) {
  python -m venv .venv
}

.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
