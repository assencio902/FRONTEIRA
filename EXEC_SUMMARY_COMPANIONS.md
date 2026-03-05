# 🎯 GUIA EXECUTIVO — SISTEMA DE COMPANHEIROS

## O Que Foi Implementado

✅ **1 Novo Endpoint Backend**  
- `GET /api/vehicles/{plate}/companions`  
- Query otimizada com JOINs mínimos  
- Detecta veículos em "companhia" (mesmo lugar + mesmo tempo + múltiplas câmeras)  

✅ **1 Toggle Frontend**  
- "Somente com companheiro" no filtro de Alvos Rastreados  
- Filtra apenas veículos que têm companions confirmados  

✅ **3 Arquivos Modificados**  
- `ingest/main.py` — Endpoint backend  
- `ingest/static/dashboard.html` — UI + lógica de filtro  
- `COMPANIONS_ENDPOINT.md` — Documentação completa  

---

## 🏃 Setup Rápido (5 min)

### Local (Windows):

```powershell
cd d:\monitoramento
git add ingest/main.py ingest/static/dashboard.html COMPANIONS_ENDPOINT.md
git commit -m "feat: sistema de detecção de companheiros (comboio inteligente)"
git push origin main
```

### VPS (Linux):

```bash
ssh user@seu-servidor.com
cd /path/to/monitoramento
git pull origin main
docker compose up -d --build
sleep 10
curl http://localhost:8000/api/vehicles/ABC1234/companions?start=2026-03-01T00:00:00&end=2026-03-05T23:59:59
```

---

## 🧪 Teste Imediato (Copiar/Colar)

### 1️⃣ Sem autenticação:

```bash
curl -s "http://localhost:8000/api/vehicles/ABC1234/companions?start=2026-03-01T00:00:00&end=2026-03-05T23:59:59" | python -m json.tool
```

**Respostas esperadas:**
```
✓ {"plate":"ABC1234","total_companions":0,"companions":[]} 
  → Veículo sem companheiros confirmados (OK!)

✓ {"plate":"ABC1234","total_companions":3,"companions":[{"companion_plate":"DEF5678","cameras_together":3,...}]}
  → Veículo com companheiros confirmados (OK!)

✗ {"detail":"HTTP 422"}
  → Data inválida (verificar formato ISO)
```

### 2️⃣ Com período customizado (últimas 24h):

```bash
# Linux/WSL/Git Bash
PLACA="ABC1234"
DATA_FIM=$(date -u +"%Y-%m-%dT%H:%M:%S")
DATA_INICIO=$(date -u -d "24 hours ago" +"%Y-%m-%dT%H:%M:%S")

curl -s "http://localhost:8000/api/vehicles/${PLACA}/companions?start=${DATA_INICIO}&end=${DATA_FIM}&delta_sec=90&min_cameras=2" \
  | python -m json.tool
```

### 3️⃣ Com autenticação JWT:

```bash
# 1. Obter token
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"senha"}' | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. Testar endpoint
curl -s "http://localhost:8000/api/vehicles/ABC1234/companions?start=2026-03-01T00:00:00&end=2026-03-05T23:59:59" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

---

## 🔍 Verificação SQL (VPS)

```bash
# Entrar no PostgreSQL
docker compose exec postgres psql -U postgres -d monitoramento

# Verificar pares detectados
SELECT a.plate, b.plate, COUNT(DISTINCT a.camera_id) AS cameras_together, COUNT(*) AS matches
FROM lpr_events a
JOIN lpr_events b ON (
    (a.camera_id = b.camera_id OR a.camera_ip = b.camera_ip)
    AND ABS(EXTRACT(EPOCH FROM (COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)))) <= 90
    AND UPPER(a.plate) != UPPER(b.plate)
)
WHERE COALESCE(a.occurred_at, a.ts) > NOW() - INTERVAL '7 days'
GROUP BY a.plate, b.plate
HAVING COUNT(DISTINCT a.camera_id) >= 2
LIMIT 10;
```

---

## 📊 O Que Muda no Dashboard

### Antes (❌ Problema):
- Multi-câmera sozinho = marcado como "ameaça" / "comboio"
- Veículo passava solo em 5 câmeras = falso positivo

### Depois (✅ Solução):
- Toggle ativado = "Somente com companheiro"
- Só mostra veículos que têm companions confirmados
- Acompanhado = detectado juntos em ≥2 câmeras + dentro de 90s

---

## 📋 Parâmetros do Endpoint

| Parâmetro | Padrão | Range | O que faz |
|-----------|--------|-------|-----------|
| `delta_sec` | 90 | 1-600 | Janela de tempo na mesma câmera (segundos) |
| `min_cameras` | 2 | 1-50 | Mínimo de câmeras onde par foi visto junto |
| `start` | — | ISO 8601 | Data/hora início |
| `end` | — | ISO 8601 | Data/hora fim |

**Exemplos:**
```
delta_sec=60&min_cameras=3  → Par confirmado em ≥3 câmeras, max 60s
delta_sec=120&min_cameras=2 → Par confirmado em ≥2 câmeras, max 120s
```

---

## 🐛 Troubleshooting

| Erro | Causa | Solução |
|------|-------|---------|
| `HTTP 404` | Endpoint não existe | `docker compose restart ingest` |
| `HTTP 422` | Data inválida | Use ISO 8601: `2026-03-01T10:30:00` |
| `HTTP 500` | Erro no banco | Ver logs: `docker compose logs ingest` |
| `{"total_companions":0}` | Veículo não tem companheiros | Normal! Teste com outro veículo |

---

## 📈 Próximas Melhorias (Opcional)

- [ ] Histórico de companheiros (timeline visual)  
- [ ] Alertas automáticos quando par é detectado  
- [ ] Relatório de "redes" (A acompanhado com B, B com C, etc)  
- [ ] Filtro dinâmico de `delta_sec` no frontend  

---

## ✅ CHECKLIST PRÉ-DEPLOY

- [ ] `git status` mostra apenas 3 arquivos modificados
- [ ] `curl` test retorna JSON válido (não HTML erro)
- [ ] Backend sobe sem erros: `docker compose logs ingest | grep -i error`
- [ ] Banco conecta: `docker compose exec postgres psql -U postgres -c "SELECT 1"`
- [ ] Índices SQL foram criados (performance OK)
- [ ] Toggle aparece no frontend
- [ ] DEV tested com 1+ placa local
- [ ] VPS deployment testado

---

## 📞 Support

**Se endpoint 404:**  
```bash
docker compose ps
docker compose logs ingest | tail -20
```

**Se slowness:**  
```sql
EXPLAIN ANALYZE SELECT ... (from COMPANIONS_ENDPOINT.md)
```

**Se dados incorretos:**  
```bash
# Verificar dados brutos
SELECT * FROM lpr_events WHERE UPPER(plate) = 'ABC1234' LIMIT 5;
```

---

**Sistema pronto para produção! 🚀**
