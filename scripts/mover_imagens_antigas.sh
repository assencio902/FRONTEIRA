#!/usr/bin/env bash
set -euo pipefail

ORIGEM="/dados/fotos_veiculos"
DESTINO="/backup/imagens_antigas/fotos_veiculos"
LOG="/backup/logs/mover_imagens_antigas.log"

LIMITE_ALTO=85
LIMITE_BAIXO=75

mkdir -p "$DESTINO"
mkdir -p "$(dirname "$LOG")"

uso_dados() {
  df -P /dados | awk 'NR==2 {gsub("%","",$5); print $5}'
}

echo "==== $(date '+%F %T') | início ====" >> "$LOG"
echo "Uso inicial de /dados: $(uso_dados)%" >> "$LOG"

while [ "$(uso_dados)" -ge "$LIMITE_ALTO" ]; do
  pasta_antiga="$(find "$ORIGEM" -mindepth 1 -maxdepth 1 -type d | sort | head -n 1)"

  if [ -z "${pasta_antiga:-}" ]; then
    echo "Nenhuma pasta encontrada em $ORIGEM para mover." | tee -a "$LOG"
    break
  fi

  nome="$(basename "$pasta_antiga")"
  echo "Movendo: $pasta_antiga -> $DESTINO/$nome" | tee -a "$LOG"
  mv "$pasta_antiga" "$DESTINO/$nome"

  uso_atual="$(uso_dados)"
  echo "Uso atual de /dados após mover: ${uso_atual}%" >> "$LOG"

  if [ "$uso_atual" -le "$LIMITE_BAIXO" ]; then
    echo "Uso de /dados caiu para ${uso_atual}%. Parando." >> "$LOG"
    break
  fi
done

echo "Uso final de /dados: $(uso_dados)%" >> "$LOG"
echo "==== $(date '+%F %T') | fim ====" >> "$LOG"
