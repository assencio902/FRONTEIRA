#!/usr/bin/env bash
set -euo pipefail

# deploy-via-scp.sh
# Copia ingest/static/dashboard.html para o servidor remoto, cria backup e reinicia o serviço ingest (docker-compose).
# Uso:
#   LOCAL_RUN: ./deploy-via-scp.sh user@server.example.com /real/path/to/monitoramento
#   ou exportar variáveis REMOTE e REMOTE_DIR

LOCAL_FILE="ingest/static/dashboard.html"
REMOTE="${1:-${REMOTE:-user@server.example.com}}"
REMOTE_DIR="${2:-${REMOTE_DIR:-/path/to/monitoramento}}"
DRY_RUN=${DRY_RUN:-0}
BACKUP_SUFFIX="$(date +%Y%m%d%H%M)"

if [ ! -f "$LOCAL_FILE" ]; then
  echo "ERRO: arquivo local não encontrado: $LOCAL_FILE" >&2
  exit 2
fi

echo "Local: $LOCAL_FILE"
echo "Remote: $REMOTE"
echo "Remote dir: $REMOTE_DIR"

if [ "$DRY_RUN" = "1" ]; then
  echo "DRY RUN: não serão feitas alterações remotas." 
fi

# copy to a temp file on remote, then mv with backup
if [ "$DRY_RUN" = "0" ]; then
  scp "$LOCAL_FILE" "$REMOTE:$REMOTE_DIR/ingest/static/dashboard.html.new"
  ssh "$REMOTE" \
    "mkdir -p '$REMOTE_DIR/ingest/static' && \
     if [ -f '$REMOTE_DIR/ingest/static/dashboard.html' ]; then cp '$REMOTE_DIR/ingest/static/dashboard.html' '$REMOTE_DIR/ingest/static/dashboard.html.bak.$BACKUP_SUFFIX'; fi && \
     mv '$REMOTE_DIR/ingest/static/dashboard.html.new' '$REMOTE_DIR/ingest/static/dashboard.html' && \
     cd '$REMOTE_DIR' && \
     if command -v docker-compose >/dev/null 2>&1; then docker-compose restart ingest || true; fi"
  echo "Deploy concluído. Backup criado com sufixo $BACKUP_SUFFIX (se existia)."
else
  echo "Comando (simulação): scp $LOCAL_FILE $REMOTE:$REMOTE_DIR/ingest/static/dashboard.html.new"
  echo "Comando (simulação): ssh $REMOTE 'mv ... && docker-compose restart ingest'"
fi

exit 0
