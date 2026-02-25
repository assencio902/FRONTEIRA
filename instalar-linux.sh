#!/bin/bash
# ============================================================
# Script de instalação do sistema de monitoramento LPR
# Ubuntu 22.04 / 24.04
# ============================================================
set -e

echo "=============================="
echo " INSTALANDO DEPENDÊNCIAS"
echo "=============================="
apt-get update -y
apt-get install -y curl git ca-certificates gnupg lsb-release ufw

echo "=============================="
echo " INSTALANDO DOCKER"
echo "=============================="
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker $SUDO_USER
    echo "Docker instalado."
else
    echo "Docker já instalado: $(docker --version)"
fi

echo "=============================="
echo " CONFIGURANDO FIREWALL (UFW)"
echo "=============================="
ufw allow ssh
ufw allow 8000/tcp comment "LPR Ingest API"
ufw allow 80/tcp   comment "HTTP"
ufw --force enable
echo "Firewall configurado."

echo "=============================="
echo " INICIANDO O SISTEMA"
echo "=============================="
cd /opt/monitoramento

# Garante que o diretório de dados existe
mkdir -p data/images data/inbox uploads

# Sobe os containers
docker compose down --remove-orphans 2>/dev/null || true
docker compose up -d --build

echo ""
echo "=============================="
echo " AGUARDANDO SERVIÇOS..."
echo "=============================="
sleep 10
docker compose ps

echo ""
echo "=============================="
echo " TESTE DO SERVIDOR"
echo "=============================="
curl -s -o /dev/null -w "HTTP Status: %{http_code}\n" \
    -X POST http://localhost:8000/api/simple-webhook

echo ""
echo "=============================="
echo " INSTALAÇÃO CONCLUÍDA!"
echo "=============================="
SERVER_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "  Servidor disponível em: http://$SERVER_IP:8000"
echo ""
echo "  Configure as câmeras:"
echo "    IP destino : $SERVER_IP"
echo "    Porta      : 8000"
echo "    URL        : /api/simple-webhook"
echo ""
echo "  Dashboard: http://$SERVER_IP:8000/static/dashboard.html"
echo "  Login: admin / admin123"
echo ""
