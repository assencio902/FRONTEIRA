# ============================================================
# Script de migração: exporta dados do Windows para o Linux
# Execute no PowerShell do Windows ANTES de migrar
# ============================================================

# 1 — Exportar banco de dados
Write-Host "Exportando banco de dados..."
docker compose exec postgres pg_dump -U monitor_user monitor > backup_monitor.sql
Write-Host "Banco exportado: backup_monitor.sql"

# 2 — Compactar projeto (sem node_modules e __pycache__)
Write-Host "Compactando projeto..."
$exclude = @('.venv', '__pycache__', '*.pyc', 'node_modules')
$files = Get-ChildItem -Path . -Recurse | Where-Object {
    $path = $_.FullName
    -not ($exclude | Where-Object { $path -like "*$_*" })
}
Compress-Archive -Path @('ingest','yolo-worker','web_ui','data','cameras.json','docker-compose.yml','backup_monitor.sql') `
    -DestinationPath monitoramento-backup.zip -Force
Write-Host "Projeto compactado: monitoramento-backup.zip"
Write-Host ""
Write-Host "Agora copie 'monitoramento-backup.zip' para o servidor Linux."
Write-Host "Exemplo via SCP:"
Write-Host "  scp monitoramento-backup.zip usuario@IP-LINUX:/opt/"
