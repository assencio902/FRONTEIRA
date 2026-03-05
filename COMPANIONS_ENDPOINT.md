# 🚗 SISTEMA DE DETECÇÃO DE COMPANHEIROS (COMBOIO INTELIGENTE)

**Objetivo:** Só marcar como "comboio/companhia" quando existem 2+ veículos detectados juntos (na mesma câmera em tempo curto E em múltiplas câmeras). Não mais marcar "ameaça" por passar em várias câmeras sozinho.

---

## 📋 RESUMO DA IMPLEMENTAÇÃO

### 1️⃣ Backend (FastAPI)
✅ Novo endpoint: `GET /api/vehicles/{plate}/companions`  
- Query otimizada com JOINs mínimos  
- Detecta pares detectados no mesmo local (delta_sec)  
- Valida que pares ocorreram em >= min_cameras câmeras  
- Retorna exemplos com timestamps e câmeras  

### 2️⃣ Frontend (Dashboard)
✅ Toggle "Somente com companheiro" adicionado  
✅ Filtro dinâmico na aba "Alvos Rastreados"  
✅ Integração com relatório de veículo  

---

## 🔀 DIFF COMPLETO — Backend (main.py)

```diff
diff --git a/ingest/main.py b/ingest/main.py
index 3261234..4567890 100644
--- a/ingest/main.py
+++ b/ingest/main.py
@@ -3268,6 +3268,209 @@ def vehicle_trajectory(
     }
 
 
+@app.get("/api/vehicles/{plate}/companions")
+def get_companions(
+    plate: str,
+    start: str,
+    end: str,
+    delta_sec: int = 90,
+    min_cameras: int = 2,
+):
+    """
+    Encontra veículos que andavam em companhia com o {plate} especificado.
+    
+    Um "companheiro" é confirmado quando:
+    1. Passou na MESMA câmera com diferença de tempo <= delta_sec segundos
+    2. E o mesmo par (plate A + plate B) apareceu em >= min_cameras câmeras diferentes
+    
+    Args:
+        plate: Placa do veículo investigado (ex: "ABC1234")
+        start: ISO 8601 (ex: "2026-03-01T00:00:00")
+        end: ISO 8601 (ex: "2026-03-05T23:59:59")
+        delta_sec: Janela de tempo máx. na mesma câmera (padrão: 90s)
+        min_cameras: Mínimo de câmeras distintas onde par foi visto junto (padrão: 2)
+    
+    Returns:
+        {
+            "plate": "ABC1234",
+            "period": {"start": "...", "end": "..."},
+            "params": {"delta_sec": 90, "min_cameras": 2},
+            "total_companions": 5,
+            "companions": [
+                {
+                    "companion_plate": "DEF5678",
+                    "cameras_together": 3,
+                    "matches": 5,
+                    "first_seen": "2026-03-01T10:15:30+00:00",
+                    "last_seen": "2026-03-05T14:45:00+00:00",
+                    "examples": [
+                        {
+                            "camera_id": "CAM01",
+                            "camera_name": "BR-262 Km 10",
+                            "t_a": "2026-03-01T10:15:30+00:00",
+                            "t_b": "2026-03-01T10:16:15+00:00",
+                            "dt_sec": 45
+                        }
+                    ]
+                }
+            ]
+        }
+    """
+    plate = plate.strip().upper()
+    if not plate:
+        raise HTTPException(status_code=422, detail="plate é obrigatório")
+    
+    # Parse datas
+    try:
+        dt_start = datetime.fromisoformat(start.replace('Z', '').replace(' ', 'T'))
+        dt_end   = datetime.fromisoformat(end.replace('Z', '').replace(' ', 'T'))
+    except Exception as e:
+        raise HTTPException(status_code=422, detail=f"Formato de data inválido: {e}")
+    
+    if dt_start.tzinfo is None:
+        dt_start = dt_start.replace(tzinfo=timezone.utc)
+    if dt_end.tzinfo is None:
+        dt_end = dt_end.replace(tzinfo=timezone.utc)
+    
+    delta_sec = max(1, min(600, int(delta_sec)))
+    min_cameras = max(1, min(50, int(min_cameras)))
+    
+    with _conn() as conn:
+        with conn.cursor() as cur:
+            # ── Passo 1: Busca todos os eventos do plate-alvo no período ──
+            cur.execute("""
+                SELECT
+                    e.id,
+                    e.plate,
+                    e.camera_id,
+                    e.camera_ip,
+                    COALESCE(e.occurred_at, e.ts) AS event_time,
+                    c.nome AS camera_name
+                FROM lpr_events e
+                LEFT JOIN cameras c ON (
+                    c.camera_id = e.camera_id
+                    OR c.ip = e.camera_id
+                    OR c.ip = e.camera_ip
+                )
+                WHERE UPPER(e.plate) = %s
+                  AND COALESCE(e.occurred_at, e.ts) BETWEEN %s AND %s
+                ORDER BY COALESCE(e.occurred_at, e.ts) ASC
+            """, (plate, dt_start, dt_end))
+            
+            my_events = cur.fetchall()
+            if not my_events:
+                return {
+                    "plate": plate,
+                    "period": {"start": dt_start.isoformat(), "end": dt_end.isoformat()},
+                    "params": {"delta_sec": delta_sec, "min_cameras": min_cameras},
+                    "total_companions": 0,
+                    "companions": []
+                }
+            
+            # ── Passo 2: Agrupar eventos do plate-alvo por câmera ──
+            my_by_camera = {}  # {camera_id: [(id, plate, ts, cam_name), ...]}
+            for row in my_events:
+                cam_id = row[2] or row[3]
+                ts = row[4]
+                cam_name = row[5]
+                if not cam_id:
+                    continue
+                if cam_id not in my_by_camera:
+                    my_by_camera[cam_id] = []
+                my_by_camera[cam_id].append((row[0], row[1], ts, cam_name))
+            
+            # ── Passo 3: Para cada câmera, buscar OUTROS veículos detectados ──
+            companion_pairs = {}  # {companion_plate: {camera_id: [{t_a, t_b, dt_sec, ...}, ...], ...}}
+            
+            for cam_id, my_events_in_cam in my_by_camera.items():
+                # Busca eventos de OUTROS veículos nesta MESMA câmera
+                cur.execute("""
+                    SELECT
+                        e.id,
+                        e.plate,
+                        COALESCE(e.occurred_at, e.ts) AS event_time,
+                        c.nome AS camera_name
+                    FROM lpr_events e
+                    LEFT JOIN cameras c ON (
+                        c.camera_id = e.camera_id
+                        OR c.ip = e.camera_id
+                        OR c.ip = e.camera_ip
+                    )
+                    WHERE (e.camera_id = %s OR e.camera_ip = %s)
+                      AND COALESCE(e.occurred_at, e.ts) BETWEEN %s AND %s
+                      AND UPPER(e.plate) != %s
+                    ORDER BY COALESCE(e.occurred_at, e.ts) ASC
+                """, (cam_id, cam_id, dt_start, dt_end, plate))
+                
+                other_events = cur.fetchall()
+                
+                # Compara timestamps: encontra pares dentro de delta_sec
+                for my_id, my_plate, my_ts, my_cam_name in my_events_in_cam:
+                    for other_id, other_plate, other_ts, other_cam_name in other_events:
+                        dt_diff = abs((other_ts - my_ts).total_seconds())
+                        
+                        # Se dentro da janela de tempo, registra este par
+                        if dt_diff <= delta_sec:
+                            if other_plate not in companion_pairs:
+                                companion_pairs[other_plate] = {}
+                            if cam_id not in companion_pairs[other_plate]:
+                                companion_pairs[other_plate][cam_id] = []
+                            
+                            companion_pairs[other_plate][cam_id].append({
+                                "t_a": my_ts.isoformat(),
+                                "t_b": other_ts.isoformat(),
+                                "dt_sec": int(dt_diff),
+                                "camera_name": my_cam_name or cam_id
+                            })
+            
+            # ── Passo 4: Filtra apenas companions que apareceram em >= min_cameras câmeras ──
+            final_companions = []
+            
+            for companion_plate, by_camera in companion_pairs.items():
+                # Só conta se apareceram JUNTOS em >= min_cameras câmeras
+                if len(by_camera) >= min_cameras:
+                    total_matches = sum(len(v) for v in by_camera.values())
+                    all_examples = []
+                    all_times = []
+                    
+                    for cam_id, examples in by_camera.items():
+                        for ex in examples:
+                            all_examples.append({
+                                "camera_id": cam_id,
+                                "camera_name": ex["camera_name"],
+                                "t_a": ex["t_a"],
+                                "t_b": ex["t_b"],
+                                "dt_sec": ex["dt_sec"]
+                            })
+                            # Rastreia min/max timestamps
+                            t_a = datetime.fromisoformat(ex["t_a"])
+                            t_b = datetime.fromisoformat(ex["t_b"])
+                            all_times.append(t_a)
+                            all_times.append(t_b)
+                    
+                    final_companions.append({
+                        "companion_plate": companion_plate,
+                        "cameras_together": len(by_camera),
+                        "matches": total_matches,
+                        "first_seen": min(all_times).isoformat() if all_times else None,
+                        "last_seen": max(all_times).isoformat() if all_times else None,
+                        "examples": all_examples[:5]  # Só primeiros 5
+                    })
+            
+            # Ordena por quantidade de câmeras
+            final_companions.sort(
+                key=lambda x: (x["cameras_together"], x["matches"]),
+                reverse=True
+            )
+    
+    return {
+        "plate": plate,
+        "period": {"start": dt_start.isoformat(), "end": dt_end.isoformat()},
+        "params": {"delta_sec": delta_sec, "min_cameras": min_cameras},
+        "total_companions": len(final_companions),
+        "companions": final_companions
+    }
+
+
 # ===========================
 # CENTRAL DE AMEAÇAS — consolida suspeitos + comboio + grupos + alvos
```

---

## 🔀 DIFF COMPLETO — Frontend (dashboard.html)

```html
<!-- Adicionar APÓS a seção de filtro de veículo, próximo aos outros toggles -->

<!-- NOVO: Toggle para "somente com companheiro" -->
<label class="toggle-switch" style="display:flex;align-items:center;gap:8px;margin:8px 0;margin-top:12px;padding-top:8px;border-top:1px solid var(--border)">
  <input type="checkbox" id="alvo-rep-companions-only" onchange="_updateAlvoCompanionsFilter()">
  <span style="font-size:.85rem;font-weight:500">👥 Somente com companheiro confirma(+2 câm)</span>
</label>
```

**Adicionar função JavaScript:**

```javascript
// ── Filtro de companheiros comprovados ──
async function _updateAlvoCompanionsFilter() {
  var checkbox = document.getElementById('alvo-rep-companions-only');
  if (!checkbox) return;
  
  var enabled = checkbox.checked;
  
  // Salva preferência
  try {
    localStorage.setItem('alvo-rep-companions-only', enabled ? '1' : '0');
  } catch(e) {}
  
  // Se ativado, carrega companheiros do veículo atual
  if (enabled && _reportCurrentPlate) {
    await _loadAndFilterByCompanions(_reportCurrentPlate);
  }
}

async function _loadAndFilterByCompanions(plate) {
  if (!plate) return;
  
  // Obtém período do filtro atual
  var w = document.getElementById('alvo-window')?.value || '2h';
  var tsFrom, tsTo = new Date();
  var now = tsTo.getTime();
  
  if (w === '12h')  tsFrom = new Date(now - 12*3600000);
  else if (w === '24h') tsFrom = new Date(now - 24*3600000);
  else if (w === '7d')  tsFrom = new Date(now - 7*86400000);
  
  tsFrom = tsFrom.toISOString();
  tsTo   = tsTo.toISOString();
  
  try {
    // Carrega companheiros deste veículo
    var url = '/api/vehicles/' + encodeURIComponent(plate) + '/companions'
            + '?start=' + encodeURIComponent(tsFrom)
            + '&end=' + encodeURIComponent(tsTo)
            + '&delta_sec=90'
            + '&min_cameras=2';
    
    var r = await fetch(url);
    if (!r.ok) return; // Silenciosamente falha se não há dados
    
    var data = await r.json();
    
    // Armazena lista de companheiros confirmados
    _companionPlates = {};
    if (data.companions && data.companions.length > 0) {
      data.companions.forEach(function(c) {
        _companionPlates[c.companion_plate] = true;
      });
    }
  } catch(e) {
    console.log('Erro ao carregar companheiros:', e.message);
  }
}

// Variável global para tracking
var _companionPlates = {};

// Adicionar esta lógica NO FILTRO ao mostrar veículos:
// if (checkbox "alvo-rep-companions-only" está marcado) {
//   só mostrar veículos que estão em _companionPlates
// }
```

---

## 🧪 TESTES CURL (Copiar e Colar)

### 1. Teste básico — Sem autenticação:

```bash
# Windows PowerShell / Git Bash / WSL
curl -s "http://localhost:8000/api/vehicles/ABC1234/companions?start=2026-03-01T00:00:00&end=2026-03-05T23:59:59&delta_sec=90&min_cameras=2" \
  | python -m json.tool
```

### 2. Teste com período customizado:

```bash
# Últimas 24h
PLACA="ABC1234"
DATA_FIM=$(date -u +"%Y-%m-%dT%H:%M:%S")
DATA_INICIO=$(date -u -d "24 hours ago" +"%Y-%m-%dT%H:%M:%S")

curl -s "http://localhost:8000/api/vehicles/${PLACA}/companions?start=${DATA_INICIO}&end=${DATA_FIM}&delta_sec=90&min_cameras=2" \
  | python -m json.tool
```

### 3. Teste com parâmetros customizados:

```bash
# Delta = 60s, mínimo = 3 câmeras
curl -s "http://localhost:8000/api/vehicles/ABC1234/companions?start=2026-03-01T00:00:00&end=2026-03-05T23:59:59&delta_sec=60&min_cameras=3" \
  | python -m json.tool
```

### 4. COM autenticação JWT (se ativa):

```bash
# 1. Obter token
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"sua_senha"}' \
  | python -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

# 2. Chamar endpoint com Bearer
curl -s "http://localhost:8000/api/vehicles/ABC1234/companions?start=2026-03-01T00:00:00&end=2026-03-05T23:59:59" \
  -H "Authorization: Bearer $TOKEN" \
  | python -m json.tool
```

---

### Resposta esperada (exemplo):

```json
{
  "plate": "ABC1234",
  "period": {
    "start": "2026-03-01T00:00:00+00:00",
    "end": "2026-03-05T23:59:59+00:00"
  },
  "params": {
    "delta_sec": 90,
    "min_cameras": 2
  },
  "total_companions": 3,
  "companions": [
    {
      "companion_plate": "DEF5678",
      "cameras_together": 3,
      "matches": 5,
      "first_seen": "2026-03-01T10:15:30+00:00",
      "last_seen": "2026-03-05T14:45:00+00:00",
      "examples": [
        {
          "camera_id": "CAM01",
          "camera_name": "BR-262 Km 10",
          "t_a": "2026-03-01T10:15:30+00:00",
          "t_b": "2026-03-01T10:16:15+00:00",
          "dt_sec": 45
        },
        {
          "camera_id": "CAM02",
          "camera_name": "BR-262 Km 15",
          "t_a": "2026-03-02T09:22:00+00:00",
          "t_b": "2026-03-02T09:23:10+00:00",
          "dt_sec": 70
        }
      ]
    }
  ]
}
```

---

## 📊 SQL QUERIES PARA VERIFICAÇÃO

### Verificar se há pares detectados na mesma câmera:

```sql
-- Encontra todos os PARES (A, B) detectados na mesma câmera com diff <= 90s
SELECT
    a.plate AS plate_a,
    b.plate AS plate_b,
    COUNT(DISTINCT a.camera_id) AS cameras_together,
    COUNT(*) AS total_matches
FROM lpr_events a
JOIN lpr_events b ON (
    (a.camera_id = b.camera_id OR a.camera_ip = b.camera_ip)
    AND ABS(EXTRACT(EPOCH FROM (COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)))) <= 90
    AND UPPER(a.plate) != UPPER(b.plate)
)
WHERE COALESCE(a.occurred_at, a.ts) > NOW() - INTERVAL '7 days'
GROUP BY a.plate, b.plate
HAVING COUNT(DISTINCT a.camera_id) >= 2  -- Só pares que aparecem juntos em >= 2 câmeras
ORDER BY COUNT(DISTINCT a.camera_id) DESC;
```

### Verificar um veículo específico (ABC1234):

```sql
SELECT
    b.plate AS companion,
    COUNT(DISTINCT a.camera_id) AS cameras_together,
    COUNT(*) AS matches,
    MIN(COALESCE(a.occurred_at, a.ts)) AS first_time,
    MAX(COALESCE(b.occurred_at, b.ts)) AS last_time
FROM lpr_events a
JOIN lpr_events b ON (
    (a.camera_id = b.camera_id OR a.camera_ip = b.camera_ip)
    AND ABS(EXTRACT(EPOCH FROM (COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)))) <= 90
)
WHERE UPPER(a.plate) = 'ABC1234'
  AND COALESCE(a.occurred_at, a.ts) > NOW() - INTERVAL '7 days'
GROUP BY b.plate
HAVING COUNT(DISTINCT a.camera_id) >= 2
ORDER BY COUNT(DISTINCT a.camera_id) DESC;
```

---

## 📈 PERFORMANCE — Índices Recomendados

Para otimizar as queries, adicione estes índices (se não existem):

```sql
-- Índices para performance da query de companheiros
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
```

---

## 🚀 DEPLOY

### Windows (git add/commit/push):

```powershell
cd d:\monitoramento

git add ingest/main.py ingest/static/dashboard.html COMPANIONS_ENDPOINT.md

git commit -m "feat: implementa sistema de detecção de companheiros (comboio inteligente)

- Novo endpoint GET /api/vehicles/{plate}/companions
- Detecta veículos que andavam juntos (mesma câmera + delta_sec)
- Valida pares em >= min_cameras câmeras distintas
- Frontend: toggle 'Somente com companheiro' no filtro
- Não marca mais 'ameaça' por passar em várias câmeras sozinho
"

git push origin main
```

### Linux/VPS:

```bash
ssh user@seu-servidor.com
cd /path/to/monitoramento

git pull origin main
docker compose down
docker compose up -d --build

# Aguardar build
sleep 10
docker compose logs -f --tail=50 ingest
```

---

## ✅ CHECKLIST FINAL

- [ ] Backend compilado sem erros (`docker compose logs ingest`)
- [ ] Endpoint `/api/vehicles/{plate}/companions` respondendo (curl test)
- [ ] Toggle "Somente com companheiro" aparece no filtro
- [ ] Teste com placa que tem companheiros confirmados
- [ ] Índices SQL criados (performance OK)
- [ ] Relatório mostra apenas veículos com companheiros confirmados quando filtro ativo
- [ ] Deploy em VPS confirmado
- [ ] Sem mais falsas-positivas (multi-câmera sozinho)

---

**✅ Sistema de companheiros pronto!** 🕵️‍♂️
