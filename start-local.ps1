<#
Start-local helper

Uso: execute em PowerShell na raiz do projeto:
    .\start-local.ps1

Se o Docker estiver disponível, fará `docker compose up --build`.
Caso contrário irá criar/ativar um venv e instalar dependências do serviço `ingest` e iniciar o servidor FastAPI.
#>

Write-Host "== Iniciando start-local =="

$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($docker) {
    Write-Host "Docker detectado em:$($docker.Source) - iniciando docker compose..."
    docker compose up --build
    exit $LASTEXITCODE
}

Write-Host "Docker não encontrado - executando modo sem-Docker (apenas `ingest`)"

if (-not (Test-Path -Path .venv)) {
    Write-Host "Criando ambiente virtual .venv..."
    python -m venv .venv
}

Write-Host "Ativando .venv"
& .\.venv\Scripts\Activate.ps1

Write-Host "Instalando dependências do ingest..."
pip install --upgrade pip
if (Test-Path -Path ingest\requirements.txt) {
    pip install -r ingest\requirements.txt
} else {
    Write-Host "Arquivo ingest\requirements.txt não encontrado. Abortando." -ForegroundColor Red
    exit 1
}

Write-Host "ATENÇÃO: este modo requer Postgres e Redis já disponíveis em localhost."
Write-Host "Se não tiver, instale o Docker ou inicie Postgres/Redis manualmente."

Write-Host "Definindo variáveis de ambiente de exemplo para conexão local..."
$env:POSTGRES_HOST = "localhost"
$env:POSTGRES_PORT = "5432"
$env:POSTGRES_DB = "monitor"
$env:POSTGRES_USER = "monitor_user"
$env:POSTGRES_PASSWORD = "monitor_pass"
$env:REDIS_URL = "redis://localhost:6379/0"

Write-Host "Iniciando servidor FastAPI (ingest)..."
Push-Location ingest
uvicorn main:app --host 0.0.0.0 --port 8000
Pop-Location
