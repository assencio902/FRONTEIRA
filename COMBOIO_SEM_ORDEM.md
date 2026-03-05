# Detecção de Comboio - Sistema Limpo

## Mudanças Implementadas

O endpoint `/api/batedor/grupos_comboio` foi atualizado para detectar grupos de veículos **sem exigir ordem fixa** e com **filtros simplificados**.

### ❌ Removido

- ~~direcao~~ (direção do veículo)
- ~~vehicle_type~~ (tipo de veículo)
- ~~vehicle_color~~ (cor do veículo)
- Qualquer referência a "suspeito", "ameaça" ou outros filtros legados

### ✅ Parâmetros Permitidos (apenas estes)

1. **`window`** - janela temporal (ex: `2h`, `24h`, `7d`)
2. **`co_window`** - janela de agrupamento em segundos (padrão: 300s, **máximo: 3600s = 1 hora**)
3. **`min_vehicles`** - tamanho do grupo (**apenas 2 ou 3 veículos**)
4. **`min_cameras`** - mínimo de câmeras distintas (padrão: 1)
5. **`min_passes`** - mínimo de repetições do grupo (padrão: 1, opcional)
6. **`limit`** - limite de resultados (padrão: 100)

### 🚫 Validação de Parâmetros

Se enviar parâmetros não suportados, o endpoint retorna **HTTP 400** com mensagem clara:

```json
{
  "detail": "Parâmetros não suportados: direcao, vehicle_type. Use apenas: co_window, limit, min_cameras, min_passes, min_vehicles, window"
}
```

### Regra por Câmera

Para cada câmera, se:
```
(max_timestamp das placas - min_timestamp das placas) <= co_window
```
Essa câmera conta como "**câmera válida**" para o grupo.

✅ **A ordem pode variar entre câmeras** - não há checagem de sequência!  
Exemplo: Grupo `{A, B, C}` pode aparecer como:
- Câmera 1: A → B → C
- Câmera 2: C → B → A  
- Câmera 3: B → A → C

**Todos contam como o mesmo grupo.**

---

## Formato da Resposta

```json
{
  "groups": [
    {
      "plates": ["ABC1234", "XYZ5678", "DEF9012"],
      "group_size": 3,
      "cameras_count": 4,
      "passes": 4,
      "cameras": [
        "Camera Entrada Norte",
        "Camera Pedágio BR-101",
        "Camera Praça Central",
        "Camera Saída Sul"
      ],
      "first_seen": "2026-03-05T10:15:32",
      "last_seen": "2026-03-05T10:42:18",
      "total_span_sec": 1606,
      "camera_details": [
        {
          "camera_id": "cam_norte_01",
          "cam_nome": "Camera Entrada Norte",
          "lat": -23.5505,
          "lon": -46.6333,
          "direcao": "norte",
          "first_seen": "2026-03-05T10:15:32",
          "last_seen": "2026-03-05T10:17:45",
          "span_sec": 133
        }
      ]
    }
  ],
  "total": 12,
  "window": "2h",
  "co_window": 300,
  "min_vehicles": 2,
  "min_cameras": 2,
  "min_passes": 1
}
```

---

## Exemplos de Uso

### 1. Comboios em N+ câmeras (últimas 2h), apenas pares

```powershell
# Grupos de 2 veículos vistos em pelo menos 3 câmeras
curl "http://localhost:8000/api/batedor/grupos_comboio?window=2h&min_cameras=3&min_vehicles=2"
```

### 2. Janela ampla de detecção (até 1h entre veículos)

```powershell
# co_window=3600 (1 hora, MÁXIMO permitido)
curl "http://localhost:8000/api/batedor/grupos_comboio?window=24h&co_window=3600&min_cameras=2&min_vehicles=3"
```

### 3. Filtrar por repetições (min_passes)

```powershell
# Grupos vistos pelo menos 3 vezes (em 3+ câmeras diferentes)
curl "http://localhost:8000/api/batedor/grupos_comboio?window=12h&min_vehicles=2&min_cameras=3&min_passes=3"
```

### 4. ❌ Tentando usar parâmetros antigos (ERRO)

```powershell
# Retorna HTTP 400: "Parâmetros não suportados: direcao"
curl "http://localhost:8000/api/batedor/grupos_comboio?window=6h&direcao=norte&min_cameras=2"
```

---

## Diferença da Lógica Antiga

| Aspecto | Antes | Agora |
|---------|-------|-------|
| **Ordem** | Implicitamente assumida (clusters lineares) | ❌ Ignorada (frozenset) |
| **Checagem de sequência** | Não verificada mas dependente de cluster_start | ✅ Removida - usa span (max-min) |
| **Filtros legados** | direcao, vehicle_type, vehicle_color | ❌ Removidos - retorna HTTP 400 |
| **co_window** | Sem limite | ✅ Limitado a 3600s (1 hora) |
| **min_vehicles** | 2-5+ veículos | ✅ Apenas 2 ou 3 veículos |
| **min_cameras** | ❌ Não existia | ✅ Filtro obrigatório (padrão: 1) |
| **min_passes** | ❌ Não existia | ✅ Filtro opcional (padrão: 1) |
| **Agregação** | Por câmera individual | Por conjunto de placas (multi-câmera) |
| **Relatório** | `camera_id`, `cam_nome` únicos | `cameras_count`, `passes`, lista de `cameras` |
| **Timestamps** | Por câmera | Global (min/max entre todas) |

---

## Interface do Usuário

### Controles Atualizados

A UI (`dashboard.html`) agora exibe **apenas**:

1. **📅 Janela temporal** - seletor de período (1h até 24h)
2. **📹 Mín. câmeras** - filtro de câmeras distintas (0-5+)
3. **👥 Tamanho do grupo** - **apenas 2 ou 3 veículos**
4. **⏱️ Janela p/ câm. (máx 1h)** - opções até 3600s (1 hora)
5. **🔁 Mín. passes (opcional)** - repetições do grupo (1-5+)

### ❌ Removido da UI

- ~~⬍ Direção~~
- ~~🚗 Tipo veículo~~
- ~~🎨 Cor~~

---

## Teste Rápido

```powershell
# Grupos de 2 veículos vistos em 2+ câmeras nas últimas 24h
Invoke-RestMethod -Uri "http://localhost:8000/api/batedor/grupos_comboio?window=24h&min_cameras=2&min_vehicles=2" | ConvertTo-Json -Depth 5
```

Se houver dados, você verá algo como:
```json
{
  "groups": [
    {
      "plates": ["ABC1234", "XYZ5678"],
      "cameras_count": 3,
      "passes": 3,
      "cameras": ["Cam Norte", "Cam Sul", "Cam Centro"],
      "first_seen": "2026-03-05T08:30:00",
      "last_seen": "2026-03-05T09:15:00"
    }
  ]
}
```

### Testando Validação de Parâmetros

```powershell
# Deve retornar HTTP 400
Invoke-RestMethod -Uri "http://localhost:8000/api/batedor/grupos_comboio?window=2h&direcao=norte"
# Erro: "Parâmetros não suportados: direcao. Use apenas: co_window, limit, min_cameras, min_passes, min_vehicles, window"
```

---

## Notas Técnicas

1. **Deduplicação por frozenset**: Conjuntos de placas são comparados sem considerar ordem
2. **Span temporal**: Usa `max(timestamps) - min(timestamps)` ao invés de `last - first` (mais preciso)
3. **Clustering permanece**: Janela deslizante ainda é usada para eficiência computacional
4. **Ordenação**: Prioriza `cameras_count` → `group_size` → `first_seen` (DESC)
5. **Validação rígida**: Qualquer parâmetro não reconhecido retorna HTTP 400 com mensagem clara
6. **Limites automáticos**: 
   - `co_window` é limitado automaticamente a 3600s (1 hora)
   - `min_vehicles` é limitado a 2 ou 3 (valores >3 são ajustados para 3)

---

## Script de Teste Completo

Execute o script de teste para validar todas as funcionalidades:

```powershell
.\test_comboio.ps1
```

Testes incluídos:
- ✅ Comboios em múltiplas câmeras
- ✅ Janela máxima (3600s)
- ✅ Filtro por repetições (min_passes)
- ✅ Validação de parâmetros não suportados
- ✅ Limite automático de co_window
- ✅ Detalhes por câmera

✅ **Implementação concluída** - sistema limpo e validado!
