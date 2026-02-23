# Aguarda o Docker responder
Write-Host "Aguardando Docker ficar pronto..." -ForegroundColor Yellow
$timeout = 120
$elapsed = 0
while ($elapsed -lt $timeout) {
    $result = docker info 2>&1
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 5
    $elapsed += 5
    Write-Host "  ...aguardando ($elapsed/$timeout s)"
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker nao respondeu. Abra o Docker Desktop manualmente." -ForegroundColor Red
    exit 1
}

Write-Host "Docker OK!" -ForegroundColor Green

Set-Location d:\monitoramento

# Subir postgres e redis primeiro
Write-Host "Subindo postgres e redis..." -ForegroundColor Cyan
docker compose up -d postgres redis
Start-Sleep -Seconds 10

# Subir ingest
Write-Host "Subindo ingest..." -ForegroundColor Cyan
docker compose up -d ingest
Start-Sleep -Seconds 5

# Copiar worker.py atualizado para o container antigo (evita rebuild pesado)
Write-Host "Atualizando yolo-worker..." -ForegroundColor Cyan
docker compose up -d yolo-worker
Start-Sleep -Seconds 5

# Instalar psycopg2 (dependencia que faltava na imagem antiga)
Write-Host "Instalando psycopg2 no yolo-worker..." -ForegroundColor Cyan
docker exec monitoramento-yolo-worker-1 pip install psycopg2-binary==2.9.9 -q

# Copiar worker.py atualizado
docker cp d:\monitoramento\yolo-worker\worker.py monitoramento-yolo-worker-1:/app/worker.py

# Reiniciar worker para carregar novo codigo
docker restart monitoramento-yolo-worker-1

Start-Sleep -Seconds 8

Write-Host ""
Write-Host "=== STATUS ===" -ForegroundColor Green
docker compose ps

Write-Host ""
Write-Host "=== LOGS YOLO (ultimas 5 linhas) ===" -ForegroundColor Green
docker logs monitoramento-yolo-worker-1 --tail 5

Write-Host ""
Write-Host "Tudo pronto! Acesse http://localhost:8000" -ForegroundColor Green
