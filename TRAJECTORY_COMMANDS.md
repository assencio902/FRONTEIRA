# 🚗 COMANDOS DE VERIFICAÇÃO — TRAJETÓRIA DE VEÍCULOS

**Data:** 2026-03-04  
**Sistema:** Monitoramento BPFRON — Trajetória Corrigida e Enriquecida

---

## 📋 RESUMO DAS ALTERAÇÕES

### Backend (`ingest/main.py`)
✅ Criado endpoint `/api/vehicles/{plate}/trajectory`
- Retorna pontos com lat/lon enriquecidos (JOIN com `cameras`)
- Ordenação cronológica (ASC)
- Deduplicação automática (5s por câmera)
- Timezone UTC padronizado
- Lista câmeras sem GPS

### Frontend (`ingest/static/dashboard.html`)
✅ Função `_loadTrajetoria()` atualizada
- Chama novo endpoint dedicado
- Recebe pontos já com lat/lon (sem lookup manual)
- Melhor tratamento de erros

✅ Função `_plotarTrajetoria()` simplificada
- Não precisa mais fazer lookup em `camPos`
- Pontos já vêm ordenados e enriquecidos
- Segmentação inteligente mantida (split por gap tempo/distância)

---

## 🔍 VERIFICAÇÕES NO SISTEMA

### 1. Verificar serviços Docker (VPS)

```bash
# Listar containers
docker ps -a

# Verificar serviço ingest/backend
docker compose ps ingest

# Ver logs recentes do backend
docker compose logs -f --tail=100 ingest
```

### 2. Verificar conexão database

```bash
# Entrar no container do PostgreSQL
docker compose exec postgres psql -U postgres -d monitoramento

# Ou via docker exec direto
docker exec -it <postgres_container_id> psql -U postgres -d monitoramento
```

### 3. SQL — Verificar dados existentes

```sql
-- Total de eventos com placa
SELECT COUNT(*) AS total_eventos 
FROM lpr_events 
WHERE plate IS NOT NULL AND plate != '';

-- Eventos por placa (top 10)
SELECT plate, COUNT(*) AS total 
FROM lpr_events 
WHERE plate IS NOT NULL 
GROUP BY plate 
ORDER BY total DESC 
LIMIT 10;

-- Câmeras cadastradas com GPS
SELECT camera_id, nome, latitude, longitude, direcao 
FROM cameras 
WHERE latitude IS NOT NULL AND longitude IS NOT NULL 
ORDER BY nome;

-- Câmeras SEM GPS (problema!)
SELECT camera_id, nome, ip 
FROM cameras 
WHERE latitude IS NULL OR longitude IS NULL 
ORDER BY nome;

-- Verificar eventos com timestamp e câmera válida
SELECT 
    e.plate,
    COUNT(*) AS total_passagens,
    MIN(COALESCE(e.occurred_at, e.ts)) AS primeira,
    MAX(COALESCE(e.occurred_at, e.ts)) AS ultima,
    COUNT(DISTINCT e.camera_id) AS cameras_distintas
FROM lpr_events e
WHERE e.plate = 'ABC1234'  -- TROCAR pela placa teste
GROUP BY e.plate;

-- Ver eventos recentes de uma placa específica
SELECT 
    e.id,
    e.plate,
    COALESCE(e.occurred_at, e.ts) AS event_time,
    e.camera_id,
    e.camera_ip,
    c.nome AS camera_nome,
    c.latitude,
    c.longitude,
    c.direcao
FROM lpr_events e
LEFT JOIN cameras c ON (
    c.camera_id = e.camera_id 
    OR c.ip = e.camera_id 
    OR c.ip = e.camera_ip
)
WHERE e.plate = 'ABC1234'  -- TROCAR
ORDER BY event_time DESC
LIMIT 20;
```

---

## 🧪 TESTES DA API

### 0. Setup — Obter Token JWT (se autenticação estiver ativa)

```bash
# Login para obter token
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"sua_senha"}'

# Resposta esperada:
# {"access_token":"eyJ...","token_type":"bearer"}

# Salvar token em variável
TOKEN="eyJ..."
```

### 1. Testar endpoint de eventos (antigo)

```bash
# Sem autenticação (se público)
curl -X GET "http://localhost:8000/api/events?plate=ABC1234&limit=10&dt_from=2026-03-01T00:00:00&dt_to=2026-03-05T23:59:59"

# Com autenticação
curl -X GET "http://localhost:8000/api/events?plate=ABC1234&limit=10&dt_from=2026-03-01T00:00:00&dt_to=2026-03-05T23:59:59" \
  -H "Authorization: Bearer $TOKEN"
```

### 2. Testar NOVO endpoint de trajetória ⭐

```bash
# TROCAR ABC1234 por uma placa real do seu sistema
PLACA="ABC1234"
DATA_INICIO="2026-03-01T00:00:00"
DATA_FIM="2026-03-05T23:59:59"

# Teste básico
curl -X GET "http://localhost:8000/api/vehicles/${PLACA}/trajectory?start=${DATA_INICIO}&end=${DATA_FIM}" \
  -H "Authorization: Bearer $TOKEN" \
  | python -m json.tool

# Resposta esperada:
# {
#   "plate": "ABC1234",
#   "start": "2026-03-01T00:00:00+00:00",
#   "end": "2026-03-05T23:59:59+00:00",
#   "total_points": 42,
#   "total_events": 45,
#   "cameras_without_gps": ["CAM07"],
#   "points": [
#     {
#       "event_id": 123,
#       "ts": "2026-03-01T10:15:30+00:00",
#       "lat": -20.12345,
#       "lon": -63.45678,
#       "camera_id": "192.168.1.10",
#       "camera_name": "BR-262 Km 10",
#       "direction": "CRESCENTE",
#       "confidence": 0.95,
#       "vehicle_type": "car",
#       "vehicle_color": "Branco",
#       "image_path": "/data/images/..."
#     },
#     ...
#   ]
# }
```

### 3. Testar com período customizado (últimas 12h)

```bash
# Calcular timestamps (Linux/WSL/Git Bash)
DATA_FIM=$(date -u +"%Y-%m-%dT%H:%M:%S")
DATA_INICIO=$(date -u -d "12 hours ago" +"%Y-%m-%dT%H:%M:%S")

curl -X GET "http://localhost:8000/api/vehicles/ABC1234/trajectory?start=${DATA_INICIO}&end=${DATA_FIM}&dedupe_seconds=3" \
  -H "Authorization: Bearer $TOKEN" \
  | python -m json.tool
```

### 4. Testar erro (placa inexistente)

```bash
curl -X GET "http://localhost:8000/api/vehicles/XXX9999/trajectory?start=2026-03-01T00:00:00&end=2026-03-05T23:59:59" \
  -H "Authorization: Bearer $TOKEN"

# Deve retornar:
# {"plate":"XXX9999","total_points":0,"cameras_without_gps":[],"points":[]}
```

### 5. Testar validação (data inválida)

```bash
curl -X GET "http://localhost:8000/api/vehicles/ABC1234/trajectory?start=data-invalida&end=2026-03-05" \
  -H "Authorization: Bearer $TOKEN"

# Deve retornar erro 422:
# {"detail":"Formato de data inválido: ..."}
```

---

## 🌐 TESTAR NO FRONTEND (Browser)

### 1. Abrir Dashboard
```
http://localhost:8000/dashboard
```

### 2. Testar trajetória de um veículo

**Opção A — Via Relatório de Veículo:**
1. Ir para **Batedor de Suspeitos** > **Central de Ameaças**
2. Digitar uma placa no filtro e aplicar
3. Clicar em **"📊 Relatório"** de um veículo
4. No relatório, clicar em **"🚗 Trajetória no Mapa"**
5. Selecionar período (12h, 24h, 7d, 30d ou customizado)
6. Clicar em **"▶ Ver no Mapa"**

**Opção B — Via Aba Mapa direto:**
1. Ir para aba **"🗺️ Câmeras"**
2. Clicar no botão **"🚗 Trajetória"** (canto superior direito)
3. Digitar placa
4. Selecionar período
5. Clicar em **"▶ Ver no Mapa"**

### 3. Validar visualização

✅ **O que deve aparecer:**
- Múltiplas polylines (se veículo foi/voltou)
- Cores diferentes por trecho quando há gap >10min ou >2km
- Marcadores numerados em cada passagem
- Setas direcionais entre pontos
- Marcadores **"▶ INÍCIO"** e **"■ FIM"** em cada trecho
- Linhas tracejadas conectando gaps entre trechos
- Info bar mostrando: placa + total passagens + N trechos + câmeras sem GPS

✅ **Popups nos marcadores devem mostrar:**
- Placa
- Passagem #X de Y
- Trecho N (se múltiplos)
- Câmera
- Horário

---

## 🐛 TROUBLESHOOTING

### Problema: "Nenhuma passagem encontrada"

```sql
-- Verificar se placa existe no BD
SELECT COUNT(*) FROM lpr_events WHERE plate ILIKE '%ABC%';

-- Ver placas disponíveis
SELECT DISTINCT plate FROM lpr_events 
WHERE plate IS NOT NULL 
ORDER BY plate 
LIMIT 50;
```

### Problema: "Câmeras sem GPS"

```sql
-- Atualizar coordenadas de uma câmera
UPDATE cameras 
SET latitude = -20.123456, longitude = -63.654321 
WHERE camera_id = 'CAM01';

-- Ou pelo IP
UPDATE cameras 
SET latitude = -20.123456, longitude = -63.654321 
WHERE ip = '192.168.1.10';
```

### Problema: Trajetória não aparece no mapa

**Console do navegador (F12):**
```javascript
// Ver dados carregados
console.log(_mapaTrajetoria);

// Ver se tem pontos
console.log(_mapaTrajetoria.points.length);

// Ver estatísticas
console.log(_mapaTrajetoria.stats);
```

### Problema: Erro 500 no endpoint

```bash
# Ver logs detalhados
docker compose logs -f ingest | grep -A 10 "trajectory"

# Ou via Python debugger
docker compose exec ingest python -c "from main import app; print(app.routes)"
```

---

## 🚀 DEPLOY / ATUALIZAÇÃO NA VPS

### 1. Commit e push das alterações

```bash
cd /path/to/monitoramento

git add ingest/main.py ingest/static/dashboard.html TRAJECTORY_COMMANDS.md
git commit -m "feat: implementa endpoint dedicado de trajetória com enriquecimento GPS

- Novo endpoint /api/vehicles/{plate}/trajectory com lat/lon enriquecidos
- JOIN automático com tabela cameras
- Deduplicação de eventos repetidos
- Frontend otimizado (sem lookup manual)
- Segmentação inteligente por gaps de tempo/distância
- Suporte a múltiplos trechos (ida e volta)
"
git push origin main
```

### 2. Atualizar na VPS

```bash
# SSH na VPS
ssh user@seu-servidor.com

# Ir para diretório do projeto
cd /path/to/monitoramento

# Pull das alterações
git pull origin main

# Rebuild e restart dos containers
docker compose down
docker compose up -d --build

# Verificar logs
docker compose logs -f ingest
```

### 3. Verificar se subiu

```bash
# Testar endpoint
curl http://localhost:8000/api/vehicles/ABC1234/trajectory?start=2026-03-01T00:00:00&end=2026-03-05T23:59:59

# Verificar se backend está rodando
docker compose ps

# Ver uso de recursos
docker stats
```

---

## 📊 MÉTRICAS E MONITORAMENTO

### Query SQL para estatísticas

```sql
-- Total de placas únicas
SELECT COUNT(DISTINCT plate) AS placas_unicas 
FROM lpr_events 
WHERE plate IS NOT NULL;

-- Eventos por dia (última semana)
SELECT 
    DATE(COALESCE(occurred_at, ts)) AS dia,
    COUNT(*) AS total_eventos,
    COUNT(DISTINCT plate) AS placas_diferentes,
    COUNT(DISTINCT camera_id) AS cameras_ativas
FROM lpr_events
WHERE COALESCE(occurred_at, ts) > NOW() - INTERVAL '7 days'
GROUP BY dia
ORDER BY dia DESC;

-- Câmeras mais ativas
SELECT 
    c.nome,
    COUNT(*) AS total_deteccoes,
    c.latitude,
    c.longitude
FROM lpr_events e
JOIN cameras c ON (c.camera_id = e.camera_id OR c.ip = e.camera_id)
WHERE e.ts > NOW() - INTERVAL '24 hours'
GROUP BY c.nome, c.latitude, c.longitude
ORDER BY total_deteccoes DESC
LIMIT 10;
```

---

## 📝 CHECKLIST FINAL

- [ ] Backend rodando sem erros
- [ ] Endpoint `/api/vehicles/{plate}/trajectory` respondendo
- [ ] SQL queries retornam dados
- [ ] Câmeras têm lat/lon cadastrados
- [ ] Frontend carrega trajetória corretamente
- [ ] Múltiplos trechos aparecem quando veículo vai/volta
- [ ] Cores diferentes por trecho
- [ ] Info bar mostra estatísticas corretas
- [ ] Teste com placa real confirmado
- [ ] Deploy na VPS concluído
- [ ] Logs não mostram erros

---

**✅ Sistema de trajetória CORRIGIDO e ENRIQUECIDO!** 🎯
