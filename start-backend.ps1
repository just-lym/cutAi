$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot\backend"

if (-not (Test-Path "config.local.toml")) {
  Copy-Item "config.example.toml" "config.local.toml"
  Write-Host "Created backend\config.local.toml from backend\config.example.toml."
}

if (-not (Test-Path ".venv")) {
  python -m venv .venv
}

.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
