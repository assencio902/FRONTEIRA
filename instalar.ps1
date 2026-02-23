# ============================================================
#  INSTALADOR - Sistema de Monitoramento BPFRON
#  Execute como Administrador
# ============================================================

$REPO_URL = "https://github.com/assencio902/monitoramento-bpfron.git"
$INSTALL_DIR = "C:\monitoramento-bpfron"

function Write-Step { param([string]$msg) Write-Host "`n>>> $msg" -ForegroundColor Yellow }
function Write-OK   { param([string]$msg) Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Fail { param([string]$msg) Write-Host "    [ERRO] $msg" -ForegroundColor Red; exit 1 }

Write-Host @"

  ██████╗ ██████╗ ███████╗██████╗  ██████╗ ███╗   ██╗
  ██╔══██╗██╔══██╗██╔════╝██╔══██╗██╔═══██╗████╗  ██║
  ██████╔╝██████╔╝█████╗  ██████╔╝██║   ██║██╔██╗ ██║
  ██╔══██╗██╔═══╝ ██╔══╝  ██╔══██╗██║   ██║██║╚██╗██║
  ██████╔╝██║     ██║     ██║  ██║╚██████╔╝██║ ╚████║
  ╚═════╝ ╚═╝     ╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝
  Sistema de Monitoramento - Polícia de Fronteiras e Divisas
  
"@ -ForegroundColor Green

# ---- 1. Checar se está como Admin ----
Write-Step "Verificando permissões de administrador..."
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Write-Fail "Execute este script como Administrador (botão direito > Executar como administrador)" }
Write-OK "Rodando como administrador"

# ---- 2. Checar Git ----
Write-Step "Verificando Git..."
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "    Git não encontrado. Instalando via winget..." -ForegroundColor Cyan
    winget install --id Git.Git -e --source winget --silent
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
}
Write-OK "Git disponível: $(git --version)"

# ---- 3. Checar Docker ----
Write-Step "Verificando Docker..."
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "    Docker não encontrado." -ForegroundColor Red
    Write-Host "    Baixe e instale o Docker Desktop em: https://www.docker.com/products/docker-desktop" -ForegroundColor Cyan
    Start-Process "https://www.docker.com/products/docker-desktop"
    Read-Host "    Após instalar e reiniciar o PC, execute este script novamente. Pressione Enter para sair"
    exit 1
}
Write-OK "Docker disponível: $(docker --version)"

# ---- 4. Checar se Docker está rodando ----
Write-Step "Verificando se Docker está ativo..."
$dockerRunning = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "    Docker não está rodando. Iniciando Docker Desktop..." -ForegroundColor Cyan
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    Write-Host "    Aguardando Docker iniciar (30s)..." -ForegroundColor Cyan
    Start-Sleep -Seconds 30
}
Write-OK "Docker está ativo"

# ---- 5. Clonar ou atualizar repositório ----
Write-Step "Obtendo código do sistema..."
if (Test-Path $INSTALL_DIR) {
    Write-Host "    Pasta já existe. Atualizando..." -ForegroundColor Cyan
    Set-Location $INSTALL_DIR
    git pull origin master
} else {
    git clone $REPO_URL $INSTALL_DIR
    Set-Location $INSTALL_DIR
}
Write-OK "Código atualizado em: $INSTALL_DIR"

# ---- 6. Criar pastas necessárias ----
Write-Step "Criando estrutura de pastas..."
New-Item -ItemType Directory -Force -Path "$INSTALL_DIR\data\images" | Out-Null
New-Item -ItemType Directory -Force -Path "$INSTALL_DIR\data\inbox"  | Out-Null
New-Item -ItemType Directory -Force -Path "$INSTALL_DIR\uploads"     | Out-Null
Write-OK "Pastas criadas"

# ---- 7. Subir containers ----
Write-Step "Iniciando containers Docker..."
docker compose pull
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Write-Fail "Erro ao subir containers. Verifique o Docker." }
Write-OK "Containers iniciados"

# ---- 8. Aguardar sistema subir ----
Write-Step "Aguardando sistema inicializar (15s)..."
Start-Sleep -Seconds 15

# ---- 9. Testar se está rodando ----
Write-Step "Testando acesso ao sistema..."
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000" -TimeoutSec 10 -UseBasicParsing
    Write-OK "Sistema respondendo na porta 8000"
} catch {
    Write-Host "    Sistema ainda inicializando. Aguarde alguns segundos e acesse manualmente." -ForegroundColor Yellow
}

# ---- Concluído ----
Write-Host @"

  ============================================
   INSTALAÇÃO CONCLUÍDA!
   Acesse o sistema em: http://localhost:8000
  ============================================

"@ -ForegroundColor Green

$abrir = Read-Host "Deseja abrir o sistema no navegador agora? (S/N)"
if ($abrir -eq "S" -or $abrir -eq "s") {
    Start-Process "http://localhost:8000"
}
