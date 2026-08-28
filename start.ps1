$ErrorActionPreference = "Stop"

$DeployRoot = "D:\MyProgramFiles\docker\app\cutAi"
$DataRoot = Join-Path $DeployRoot "data"

New-Item -ItemType Directory -Force -Path $DeployRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot "postgres") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot "redis") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot "aicut") | Out-Null

docker compose --project-name aicut-services up -d

Write-Host ""
Write-Host "AICut dependency services are running:"
Write-Host "  PostgreSQL: localhost:5432"
Write-Host "  Redis:      localhost:6379"
Write-Host "  Data:       $DataRoot"
Write-Host ""
Write-Host "Start backend locally with:  .\start-backend.ps1"
Write-Host "Start frontend locally with: .\start-frontend.ps1"
