# 📋 COPIAR/COLAR — TUDO PRONTO PARA DEPLOY

## 1️⃣ WINDOWS — Commit & Push (Copiar/Colar)

```powershell
cd d:\monitoramento
git add ingest/main.py ingest/static/dashboard.html COMPANIONS_ENDPOINT.md EXEC_SUMMARY_COMPANIONS.md
git commit -m "feat: sistema de detecção de companheiros (comboio inteligente)

- Novo endpoint GET /api/vehicles/{plate}/companions
- Detecta veículos acompanhados em >= 2 câmeras com gap <= 90s
- Frontend: toggle 'Somente com companheiro' no filtro
- Elimina falsas-positivas de multi-câmera sozinho
- Query otimizada com índices sugeridos
"
git push origin main
```

---

## 2️⃣ VPS — Deploy (Copiar/Colar)

```bash
ssh user@seu-servidor.com
cd /path/to/monitoramento
git pull origin main
docker compose down
docker compose up -d --build
sleep 15
docker compose logs -f ingest | tail -30
```

**Verificar if online (Ctrl+C after):**
```bash
curl -s http://localhost:8000/api/vehicles/ABC1234/companions?start=2026-03-01T00:00:00&end=2026-03-05T23:59:59 | head -50
```

---

## 3️⃣ TESTES — Curl Commands (Copiar/Colar)

### Test 1: Placa sem companheiros

```bash
curl -s "http://localhost:8000/api/vehicles/XYZ1234/companions?start=2026-03-01T00:00:00&end=2026-03-05T23:59:59" | python -m json.tool
```

**Esperado:**
```json
{
  "plate": "XYZ1234",
  "total_companions": 0,
  "companions": []
}
```

### Test 2: Placa com companheiros (substituir ABC1234)

```bash
curl -s "http://localhost:8000/api/vehicles/ABC1234/companions?start=2026-03-01T00:00:00&end=2026-03-05T23:59:59" | python -m json.tool
```

**Esperado se tem companheiros:**
```json
{
  "plate": "ABC1234",
  "period": {"start": "...", "end": "..."},
  "params": {"delta_sec": 90, "min_cameras": 2},
  "total_companions": 2,
  "companions": [
    {
      "companion_plate": "DEF5678",
      "cameras_together": 3,
      "matches": 5,
      "first_seen": "2026-03-01T...",
      "last_seen": "2026-03-05T...",
      "examples": [...]
    }
  ]
}
```

### Test 3: Com período customizado (últimas 24h)

```bash
# Para Linux/WSL/Git Bash:
PLACA="ABC1234"
DATA_FIM=$(date -u +"%Y-%m-%dT%H:%M:%S")
DATA_INICIO=$(date -u -d "24 hours ago" +"%Y-%m-%dT%H:%M:%S")
curl -s "http://localhost:8000/api/vehicles/${PLACA}/companions?start=${DATA_INICIO}&end=${DATA_FIM}" | python -m json.tool

# Para PowerShell Windows:
$END=(Get-Date -AsUTC -Format "yyyy-MM-ddTHH:mm:ss")
$START=(Get-Date -AsUTC).AddHours(-24).ToString("yyyy-MM-ddTHH:mm:ss")
curl.exe -s "http://localhost:8000/api/vehicles/ABC1234/companions?start=$START&end=$END" | python -m json.tool
```

### Test 4: Com parâmetros customizados

```bash
# Delta = 60s (ao invés de 90s), min = 3 câmeras
curl -s "http://localhost:8000/api/vehicles/ABC1234/companions?start=2026-03-01T00:00:00&end=2026-03-05T23:59:59&delta_sec=60&min_cameras=3" | python -m json.tool
```

### Test 5: Com autenticação JWT

```bash
# 1. Obter token
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"sua_senha"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo $TOKEN

# 2. Usar token
curl -s "http://localhost:8000/api/vehicles/ABC1234/companions?start=2026-03-01T00:00:00&end=2026-03-05T23:59:59" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

---

## 4️⃣ ÍNDICES SQL (Copiar/Cola no psql)

```sql
-- Acessar o banco na VPS
docker compose exec postgres psql -U postgres -d monitoramento

-- Copiar e colar isto no prompt SQL:
CREATE INDEX IF NOT EXISTS idx_lpr_camera_ts ON lpr_events(
    COALESCE(camera_id, camera_ip),
    COALESCE(occurred_at, ts)
);

CREATE INDEX IF NOT EXISTS idx_lpr_plate_ts ON lpr_events(
    plate,
    COALESCE(occurred_at, ts)
);

CREATE INDEX IF NOT EXISTS idx_cameras_id ON cameras(camera_id);
CREATE INDEX IF NOT EXISTS idx_cameras_ip ON cameras(ip);

-- Verificar índices criados:
\di idx_*
```

---

## 5️⃣ VERIFICAR SE ESTÁ ONLINE

```bash
# Rápido (1 linha)
curl -s http://localhost:8000/api/vehicles/ABC1234/companions?start=2026-03-01T00:00:00&end=2026-03-05T23:59:59 && echo "✓ OK" || echo "✗ ERRO"

# Detalhado
curl -v http://localhost:8000/api/vehicles/ABC1234/companions?start=2026-03-01T00:00:00&end=2026-03-05T23:59:59 2>&1 | grep -E "^(<|>|Connected|HTTP)"
```

---

## 6️⃣ LOGS E TROUBLESHOOTING

```bash
# Ver logs em tempo real
docker compose logs -f ingest

# Ver últimas 50 linhas
docker compose logs --tail=50 ingest

# Filtrar por erro
docker compose logs ingest | grep -i error

# Ver logs do PostgreSQL
docker compose logs postgres | tail -20

# Status dos containers
docker compose ps

# Resetar tudo (CAREFUL!)
docker compose down -v
docker compose up -d --build
```

---

## 7️⃣ REVERTER SE NECESSÁRIO

```bash
# Se algo deu errado, voltar ao commit anterior
git revert HEAD --no-edit
git push origin main

# Ou hard reset (PERIGO — perde commits)
git reset --hard HEAD~1
git push -f origin main
```

---

## 8️⃣ VERIFICAR DADOS NO BANCO

```bash
# Acessar PostgreSQL
docker compose exec postgres psql -U postgres -d monitoramento

-- Ver placas com múltiplas detecções
SELECT 
    a.plate, 
    b.plate, 
    COUNT(DISTINCT a.camera_id) as cameras_together,
    COUNT(*) as times_detected
FROM lpr_events a
JOIN lpr_events b ON (
    (a.camera_id = b.camera_id OR a.camera_ip = b.camera_ip)
    AND ABS(EXTRACT(EPOCH FROM (COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)))) <= 90
    AND UPPER(a.plate) != UPPER(b.plate)
)
WHERE COALESCE(a.occurred_at, a.ts) > NOW() - INTERVAL '7 days'
GROUP BY a.plate, b.plate
HAVING COUNT(DISTINCT a.camera_id) >= 2
ORDER BY cameras_together DESC
LIMIT 20;
```

---

## 9️⃣ FINAL CHECKLIST

```
[ ] git add/commit/push completado no Windows
[ ] git pull/up -d --build completado no VPS
[ ] curl test 1 retorna JSON válido
[ ] curl test 2 com autenticação funciona
[ ] índices SQL estão criados
[ ] docker compose ps mostra ingest verde/healthy
[ ] toggle "Somente com companheiro apareça no frontend
[ ] 0 erros em docker compose logs
[ ] Documentação revisada (COMPANIONS_ENDPOINT.md)
```

---

**✅ Sistema de Companheiros — PRONTO PARA PRODUÇÃO**

Todos os arquivos estão em:
- `ingest/main.py` — Backend
- `ingest/static/dashboard.html` — Frontend UI
- `COMPANIONS_ENDPOINT.md` — Docs completa
- Este arquivo — Guia copiar/colar

**Você está pronto!** 🚀
