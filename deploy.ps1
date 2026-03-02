# ============================================================
# deploy.ps1 — Envia atualizacao para a VPS via SSH
# Uso: .\deploy.ps1 -Host "SEU_IP" -User "SEU_USUARIO"
# ============================================================
param(
    [Parameter(Mandatory)][string]$VpsHost,
    [Parameter(Mandatory)][string]$VpsUser,
    [string]$RemoteDir = "/opt/monitoramento"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== DEPLOY BPFRON ===" -ForegroundColor Cyan
Write-Host "VPS: $VpsUser@$VpsHost" -ForegroundColor Yellow
Write-Host "Dir: $RemoteDir" -ForegroundColor Yellow
Write-Host ""

# Comando executado remotamente via SSH
$remoteCmd = @"
set -e
echo '--- Git pull ---'
cd $RemoteDir
git pull origin main

echo '--- Rebuild containers (modo CPU para VPS) ---'
docker compose -f docker-compose.yml -f docker-compose.vps.yml build ingest yolo-worker

echo '--- Subindo servicos ---'
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d --no-deps ingest yolo-worker

echo '--- Status ---'
docker compose -f docker-compose.yml -f docker-compose.vps.yml ps
echo 'Deploy concluido!'
"@

Write-Host "Conectando na VPS e executando deploy..." -ForegroundColor Cyan
ssh "$VpsUser@$VpsHost" $remoteCmd

Write-Host ""
Write-Host "Deploy finalizado!" -ForegroundColor Green
